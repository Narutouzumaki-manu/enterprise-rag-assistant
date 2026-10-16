from dataclasses import FrozenInstanceError

import pytest

from app.agents.config import AgentConfig


def test_defaults_match_the_trd():
    config = AgentConfig()
    assert config.top_k == 8
    assert config.widened_top_k == 15
    assert config.max_subqueries == 5
    assert config.max_retries == 2
    assert config.max_steps == 12
    assert config.max_evidence_chunks == 20
    assert config.coverage_threshold == 0.8
    assert config.use_similarity_hint is False
    assert config.llm_retries == 1
    assert config.max_confidence == 0.95
    assert config.use_rewrites is False
    assert config.quarantine_instructions is True


def test_config_is_frozen():
    config = AgentConfig()
    with pytest.raises(FrozenInstanceError):
        config.max_steps = 99


def test_two_retries_fit_inside_the_default_step_cap():
    # first pass 4 steps + 2 retries x 3 steps = 10, cap is 12
    config = AgentConfig()
    assert 4 + 3 * config.max_retries <= config.max_steps


def test_max_steps_too_small_for_retries_is_rejected():
    with pytest.raises(ValueError, match="need at least 13"):
        AgentConfig(max_retries=3)


def test_consistent_retry_and_step_change_is_accepted():
    config = AgentConfig(max_retries=3, max_steps=13)
    assert config.max_retries == 3


def test_zero_retries_is_allowed():
    assert AgentConfig(max_retries=0, max_steps=4).max_retries == 0


def test_widened_top_k_above_backend_limit_is_rejected():
    with pytest.raises(ValueError, match="widened_top_k"):
        AgentConfig(widened_top_k=25)


def test_widened_top_k_below_top_k_is_rejected():
    with pytest.raises(ValueError, match="widened_top_k"):
        AgentConfig(top_k=10, widened_top_k=5)


@pytest.mark.parametrize("bad_top_k", [0, 21])
def test_top_k_outside_range_is_rejected(bad_top_k):
    with pytest.raises(ValueError, match="top_k"):
        AgentConfig(top_k=bad_top_k)


@pytest.mark.parametrize("bad_threshold", [-0.1, 1.1])
def test_coverage_threshold_outside_zero_to_one_is_rejected(bad_threshold):
    with pytest.raises(ValueError, match="coverage_threshold"):
        AgentConfig(coverage_threshold=bad_threshold)


def test_zero_subqueries_is_rejected():
    with pytest.raises(ValueError, match="max_subqueries"):
        AgentConfig(max_subqueries=0)


def test_zero_evidence_chunks_is_rejected():
    with pytest.raises(ValueError, match="max_evidence_chunks"):
        AgentConfig(max_evidence_chunks=0)


def test_negative_retries_is_rejected():
    with pytest.raises(ValueError, match="max_retries"):
        AgentConfig(max_retries=-1)


def test_negative_llm_retries_is_rejected():
    with pytest.raises(ValueError, match="llm_retries"):
        AgentConfig(llm_retries=-1)


@pytest.mark.parametrize("bad_confidence", [0.0, 1.1])
def test_max_confidence_outside_range_is_rejected(bad_confidence):
    with pytest.raises(ValueError, match="max_confidence"):
        AgentConfig(max_confidence=bad_confidence)