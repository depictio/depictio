# import pytest
# from bson import ObjectId

# from .models import DummyModel, HelloModel
# from depictio_models.utils import convert_model_to_dict, validate_model_config


# def test_convert_model_to_dict():
#     # Create a dummy ObjectId and instantiate the dummy model.
#     dummy_id = ObjectId("507f1f77bcf86cd799439011")
#     model = DummyModel(name="test", id=dummy_id)

#     # Convert the model to a dictionary.
#     result = convert_model_to_dict(model)

#     # Assert that the result is a dictionary.
#     assert isinstance(result, dict)

#     # Assert that the 'id' field has been converted to a string.
#     assert isinstance(result["id"], str)
#     assert result["id"] == str(dummy_id)

#     # Assert that the 'name' field remains unchanged.
#     assert result["name"] == "test"


# # Test case for validating a correct configuration
# def test_validate_model_config_valid():
#     """
#     Test the validate_model_config function with a valid configuration.

#     Asserts:
#         The key1 and key2 in the result configuration match the input values.
#     """
#     config = {"key1": "value1", "key2": 123}
#     result = validate_model_config(config, HelloModel)
#     assert result.key1 == "value1"
#     assert result.key2 == 123


# # Test case for validating a configuration with an invalid type
# def test_validate_model_config_invalid_type():
#     """
#     Test the validate_model_config function with an invalid type for key2.

#     Asserts:
#         A ValueError is raised due to the invalid type.
#     """
#     config = {"key1": "value1", "key2": "not_an_int"}
#     with pytest.raises(ValueError):
#         validate_model_config(config, HelloModel)


# # Test case for validating a configuration with a missing key
# def test_validate_model_config_missing_key():
#     """
#     Test the validate_model_config function with a missing key in the configuration.

#     Asserts:
#         A ValueError is raised due to the missing key.
#     """
#     config = {"key1": "value1"}
#     with pytest.raises(ValueError):
#         validate_model_config(config, HelloModel)


# # Test case for validating a configuration with environment variables
# def test_validate_model_config_with_env_vars(monkeypatch):
#     """
#     Test the validate_model_config function with environment variables.

#     This test sets an environment variable using monkeypatch and verifies that
#     the validate_model_config function correctly substitutes the environment variable
#     value in the configuration.

#     Args:
#         monkeypatch: pytest's monkeypatch fixture used to set environment variables.

#     Asserts:
#         The key1 in the result configuration is substituted with the environment
#         variable value.
#         The key2 in the result configuration remains unchanged.
#     """
#     monkeypatch.setenv("TEST_ENV_VAR", "env_value")
#     config = {"key1": "${TEST_ENV_VAR}", "key2": 123}
#     result = validate_model_config(config, HelloModel)
#     assert result.key1 == "env_value"
#     assert result.key2 == 123


# # Test case for validating a configuration with an invalid config type
# def test_validate_model_config_invalid_config_type():
#     """
#     Test the validate_model_config function with an invalid configuration type.

#     Asserts:
#         A ValueError is raised due to the invalid configuration type.
#     """
#     config = ["not", "a", "dict"]
#     with pytest.raises(ValueError):
#         validate_model_config(config, HelloModel)
