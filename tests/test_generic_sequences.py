"""Tests de las invariantes cruzadas de `ControlFollowupFamily` (cierre de
hardening §A4, v1.7): el catálogo declarado por el `AlternativeGroup`
compartido y las secuencias reales de `alternatives` no pueden divergir —
ni duplicadas, ni faltantes, ni sobrantes, ni con `sequence_id` repetidos,
ni con un `opening.steps` que no sea EXACTAMENTE (campo a campo) el
prefijo de cada alternativa. Todo con actores/mecánicas SINTÉTICOS — nada
de esto es Darius, Mordekaiser, Garen ni Kennen. No hay motor de
transición ni generador de escenarios en este archivo."""

from __future__ import annotations

import pytest

from lol_reasoner.domain.enums import Support
from lol_reasoner.reasoning.sequences.generic_sequences import (
    ControlFollowupFamily,
    FollowupAlternative,
    build_control_into_stack_sequences,
    extend_family_alternatives_with_step,
)
from lol_reasoner.reasoning.sequences.sequence import AlternativeGroup, InteractionSequence
from lol_reasoner.reasoning.sequences.steps import (
    WHOLE_EFFECT_COMPONENT,
    ActorRole,
    EffectIdentity,
    SequenceStep,
)

# --- fixtures sintéticas -----------------------------------------------------


def _identity(component: str = WHOLE_EFFECT_COMPONENT, causal_role: str = "stack_application") -> EffectIdentity:
    return EffectIdentity(fact_ref="synthetic:mechanic", causal_role=causal_role, component=component)


def _control_step(step_id: str = "control") -> SequenceStep:
    return SequenceStep(
        step_id=step_id,
        action_ref="candidate:control",
        actor=ActorRole.CANDIDATE,
        declared_support=Support.STRUCTURAL,
    )


def _followup_step(step_id: str) -> SequenceStep:
    return SequenceStep(
        step_id=step_id,
        action_ref=f"candidate:{step_id}",
        actor=ActorRole.CANDIDATE,
        declared_support=Support.STRUCTURAL,
        consumes=(_identity(),),
    )


def _valid_family(alternative_ids: tuple[str, ...] = ("aa", "q")) -> ControlFollowupFamily:
    control_step = _control_step()
    group = AlternativeGroup(group_id="g", alternative_ids=alternative_ids)
    opening = InteractionSequence(sequence_id="fam:opening", steps=(control_step,))
    alternatives = tuple(
        InteractionSequence(
            sequence_id=f"fam:{alt_id}",
            steps=(control_step, _followup_step(alt_id)),
            alternative_group=group,
            alternative_id=alt_id,
        )
        for alt_id in alternative_ids
    )
    return ControlFollowupFamily(opening=opening, alternatives=alternatives)


# --- real builder (registry-agnostic) sigue produciendo familias válidas ----


def test_build_control_into_stack_sequences_produces_a_valid_family():
    followups = (
        FollowupAlternative(
            alternative_id="aa",
            step_id="followup_aa",
            action_ref="candidate:aa",
            ability_slot=None,
            consumes=_identity(),
            stack_target=ActorRole.ENEMY,
            stack_reference="synthetic_stack",
        ),
        FollowupAlternative(
            alternative_id="q",
            step_id="followup_q",
            action_ref="candidate:q",
            ability_slot="q",
            consumes=_identity(component="outer"),
            stack_target=ActorRole.ENEMY,
            stack_reference="synthetic_stack",
        ),
    )
    family = build_control_into_stack_sequences(
        group_id="g",
        control_actor=ActorRole.CANDIDATE,
        control_step_id="control",
        control_action_ref="candidate:control",
        control_ability_slot="e",
        control_consumes=_identity(causal_role="displacement"),
        followups=followups,
        sequence_id_prefix="fam",
    )
    assert {alt.alternative_id for alt in family.alternatives} == {"aa", "q"}
    assert family.pending_group.alternative_ids == ("aa", "q")
    assert family.pending_group.selected_id is None


def test_extend_family_alternatives_with_step_preserves_validity():
    family = _valid_family()
    extra_step = SequenceStep(
        step_id="response",
        action_ref="enemy:response",
        actor=ActorRole.ENEMY,
        declared_support=Support.STRUCTURAL,
    )
    extended = extend_family_alternatives_with_step(family, extra_step=extra_step)
    assert all(alt.steps[-1] == extra_step for alt in extended.alternatives)
    assert extended.opening == family.opening  # opening intacto


# ---------------------------------------------------------------------------
# §A4 — bijección catálogo <-> secuencias
# ---------------------------------------------------------------------------


def test_family_with_a_valid_catalog_is_accepted():
    family = _valid_family()
    assert {alt.alternative_id for alt in family.alternatives} == {"aa", "q"}


def test_duplicate_sequences_for_the_same_alternative_id_is_rejected():
    control_step = _control_step()
    group = AlternativeGroup(group_id="g", alternative_ids=("aa", "q"))
    opening = InteractionSequence(sequence_id="fam:opening", steps=(control_step,))
    # DOS secuencias distintas, ambas declarando alternative_id="q"
    duplicated = (
        InteractionSequence(
            sequence_id="fam:aa", steps=(control_step, _followup_step("aa")),
            alternative_group=group, alternative_id="aa",
        ),
        InteractionSequence(
            sequence_id="fam:q_1", steps=(control_step, _followup_step("q1")),
            alternative_group=group, alternative_id="q",
        ),
        InteractionSequence(
            sequence_id="fam:q_2", steps=(control_step, _followup_step("q2")),
            alternative_group=group, alternative_id="q",
        ),
    )
    with pytest.raises(ValueError, match="DUPLICADAS"):
        ControlFollowupFamily(opening=opening, alternatives=duplicated)


def test_alternative_id_missing_a_sequence_is_rejected():
    control_step = _control_step()
    # el grupo declara TRES alternativas ("aa", "q", "w") pero solo hay
    # secuencias para dos
    group = AlternativeGroup(group_id="g", alternative_ids=("aa", "q", "w"))
    opening = InteractionSequence(sequence_id="fam:opening", steps=(control_step,))
    alternatives = (
        InteractionSequence(
            sequence_id="fam:aa", steps=(control_step, _followup_step("aa")),
            alternative_group=group, alternative_id="aa",
        ),
        InteractionSequence(
            sequence_id="fam:q", steps=(control_step, _followup_step("q")),
            alternative_group=group, alternative_id="q",
        ),
    )
    with pytest.raises(ValueError, match="'w'"):
        ControlFollowupFamily(opening=opening, alternatives=alternatives)


def test_alternative_group_with_a_different_catalog_is_rejected_before_reaching_extra_check():
    # Nota de diseño: "una secuencia con alternative_id ajeno al catálogo"
    # (la mitad "sobrante" de la bijección de §A4) es estructuralmente
    # INALCANZABLE de forma aislada, porque `InteractionSequence` (ronda
    # anterior) ya exige que `alternative_id` pertenezca a su PROPIO
    # `alternative_group.alternative_ids` — así que la única forma de que
    # una alternativa declare un id "de más" es que su grupo declare un
    # catálogo DISTINTO del resto, lo cual la guarda de "mismo group_id/
    # alternative_ids para todas las alternativas" (ya existente) rechaza
    # primero. Se conserva la comprobación de "sobrantes" en el código por
    # profundidad de defensa (si esa guarda anterior cambiara alguna vez),
    # pero hoy este es el único camino real hacia un catálogo divergente.
    control_step = _control_step()
    group_ab = AlternativeGroup(group_id="g", alternative_ids=("aa", "q"))
    group_extended = AlternativeGroup(group_id="g", alternative_ids=("aa", "q", "w"))
    opening = InteractionSequence(sequence_id="fam:opening", steps=(control_step,))
    alternatives = (
        InteractionSequence(
            sequence_id="fam:aa", steps=(control_step, _followup_step("aa")),
            alternative_group=group_ab, alternative_id="aa",
        ),
        InteractionSequence(
            sequence_id="fam:w", steps=(control_step, _followup_step("w")),
            alternative_group=group_extended, alternative_id="w",
        ),
    )
    with pytest.raises(ValueError, match="MISMO group_id"):
        ControlFollowupFamily(opening=opening, alternatives=alternatives)


# ---------------------------------------------------------------------------
# §A4 — sequence_id únicos
# ---------------------------------------------------------------------------


def test_duplicate_sequence_id_between_alternative_and_opening_is_rejected():
    control_step = _control_step()
    group = AlternativeGroup(group_id="g", alternative_ids=("aa", "q"))
    # la alternativa "aa" reutiliza, por error, el sequence_id de opening
    opening = InteractionSequence(sequence_id="fam:shared", steps=(control_step,))
    alternatives = (
        InteractionSequence(
            sequence_id="fam:shared",  # colisión con opening.sequence_id
            steps=(control_step, _followup_step("aa")),
            alternative_group=group, alternative_id="aa",
        ),
        InteractionSequence(
            sequence_id="fam:q", steps=(control_step, _followup_step("q")),
            alternative_group=group, alternative_id="q",
        ),
    )
    with pytest.raises(ValueError, match="sequence_id repetidos"):
        ControlFollowupFamily(opening=opening, alternatives=alternatives)


# ---------------------------------------------------------------------------
# §A4 — opening.steps como prefijo ESTRUCTURAL de cada alternativa
# ---------------------------------------------------------------------------


def test_alternative_with_a_structurally_different_control_step_is_rejected():
    control_step = _control_step()
    # un control_step "parecido" pero con OTRO declared_support — mismo
    # step_id/action_ref, pero NO es estructuralmente idéntico.
    diverging_control_step = SequenceStep(
        step_id="control",
        action_ref="candidate:control",
        actor=ActorRole.CANDIDATE,
        declared_support=Support.CONDITIONED,  # distinto del STRUCTURAL de arriba
    )
    group = AlternativeGroup(group_id="g", alternative_ids=("aa", "q"))
    opening = InteractionSequence(sequence_id="fam:opening", steps=(control_step,))
    alternatives = (
        InteractionSequence(
            sequence_id="fam:aa", steps=(diverging_control_step, _followup_step("aa")),
            alternative_group=group, alternative_id="aa",
        ),
        InteractionSequence(
            sequence_id="fam:q", steps=(control_step, _followup_step("q")),
            alternative_group=group, alternative_id="q",
        ),
    )
    with pytest.raises(ValueError, match="prefijo"):
        ControlFollowupFamily(opening=opening, alternatives=alternatives)


def test_alternative_missing_the_control_step_entirely_is_rejected():
    control_step = _control_step()
    group = AlternativeGroup(group_id="g", alternative_ids=("aa", "q"))
    opening = InteractionSequence(sequence_id="fam:opening", steps=(control_step,))
    alternatives = (
        # "aa" empieza directamente con su follow-up, sin el control compartido
        InteractionSequence(
            sequence_id="fam:aa", steps=(_followup_step("aa"),),
            alternative_group=group, alternative_id="aa",
        ),
        InteractionSequence(
            sequence_id="fam:q", steps=(control_step, _followup_step("q")),
            alternative_group=group, alternative_id="q",
        ),
    )
    with pytest.raises(ValueError, match="prefijo"):
        ControlFollowupFamily(opening=opening, alternatives=alternatives)
