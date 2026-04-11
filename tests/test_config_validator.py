# tests/test_config_validator.py
import pytest
from hi_agent.config.validator import ConfigValidator, ConfigValidationError

def test_valid_config_passes():
    v = ConfigValidator(env="prod")
    data = {"server_port": 8080, "context_health_green_threshold": 0.70}
    result = v.validate(data)
    assert result["server_port"] == 8080

def test_invalid_type_prod_raises():
    v = ConfigValidator(env="prod")
    with pytest.raises(ConfigValidationError) as exc_info:
        v.validate({"server_port": "not_an_int"})
    assert "server_port" in str(exc_info.value)

def test_invalid_type_dev_returns_default(caplog):
    import logging
    v = ConfigValidator(env="dev")
    with caplog.at_level(logging.WARNING):
        result = v.validate({"server_port": "not_an_int"})
    assert result["server_port"] == 8080  # TraceConfig default
    assert "server_port" in caplog.text

def test_threshold_out_of_range_prod_raises():
    v = ConfigValidator(env="prod")
    with pytest.raises(ConfigValidationError):
        v.validate({"context_health_green_threshold": 1.5})

def test_cross_field_constraint_green_lt_yellow():
    v = ConfigValidator(env="prod")
    with pytest.raises(ConfigValidationError) as exc_info:
        v.validate({
            "context_health_green_threshold": 0.90,
            "context_health_yellow_threshold": 0.80,  # yellow < green → invalid
        })
    assert "green_threshold" in str(exc_info.value)

def test_dev_mode_cross_field_falls_back(caplog):
    import logging
    v = ConfigValidator(env="dev")
    with caplog.at_level(logging.WARNING):
        result = v.validate({
            "context_health_green_threshold": 0.90,
            "context_health_yellow_threshold": 0.80,
        })
    # Should fall back to defaults for both conflicting fields
    assert result["context_health_green_threshold"] == 0.70
    assert result["context_health_yellow_threshold"] == 0.85

def test_unknown_fields_ignored():
    v = ConfigValidator(env="prod")
    result = v.validate({"server_port": 9000, "unknown_key": "ignored"})
    assert "unknown_key" not in result

def test_env_from_environment_variable(monkeypatch):
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    v = ConfigValidator.from_env()
    assert v.env == "dev"
