import sys
import types

if 'pydantic.warnings' not in sys.modules:
    warnings_mod = types.ModuleType('pydantic.warnings')
    class PydanticDeprecatedSince20(Warning):
        pass
    warnings_mod.PydanticDeprecatedSince20 = PydanticDeprecatedSince20
    sys.modules['pydantic.warnings'] = warnings_mod
