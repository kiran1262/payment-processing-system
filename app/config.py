from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = f"sqlite:///{(BASE_DIR / 'payment.db').as_posix()}"
APP_NAME = "Payment"
