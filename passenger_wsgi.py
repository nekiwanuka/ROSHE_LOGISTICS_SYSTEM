import os
import traceback
from pathlib import Path


def _safe_startup_log(message: str) -> None:
	"""Best-effort logging for early Passenger startup failures."""
	try:
		log_path = Path(__file__).resolve().parent / "passenger_startup.log"
		with log_path.open("a", encoding="utf-8") as f:
			f.write(message.rstrip("\n") + "\n")
	except Exception:
		# Never block app startup due to logging issues.
		pass


try:
	# cPanel Passenger looks for a module-level `application`.
	os.environ.setdefault("DJANGO_SETTINGS_MODULE", "roshe_logistics.settings")
	from roshe_logistics.wsgi import application  # noqa: E402
except Exception:
	base_dir = Path(__file__).resolve().parent
	_safe_startup_log("=== Passenger startup error ===")
	_safe_startup_log(f"CWD: {os.getcwd()}")
	_safe_startup_log(f"BASE_DIR: {base_dir}")
	_safe_startup_log(f".env exists: {(base_dir / '.env').exists()}")
	_safe_startup_log(traceback.format_exc())
	raise
