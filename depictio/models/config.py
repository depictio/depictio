# depictio_models/config.py

from depictio.models.utils import get_depictio_context

DEPICTIO_CONTEXT = get_depictio_context()
# DEPICTIO_CONTEXT = os.getenv("DEPICTIO_CONTEXT")
print(f"DEPICTIO_CONTEXT: {DEPICTIO_CONTEXT}")
