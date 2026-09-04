from pathlib import Path
import subprocess
import textwrap
import pytest
from pydantic import ValidationError
from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[3]


def test_production_rejects_default_jwt_secret():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret="dev-only-change-me",
            database_url="postgresql+psycopg://aastha:verystrongpassword@db:5432/aastha",
            api_cors_origins="https://crm.aastha.test",
            trusted_hosts="crm.aastha.test",
        )


def test_production_rejects_wildcard_cors():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret="x" * 64,
            database_url="postgresql+psycopg://aastha:verystrongpassword@db:5432/aastha",
            api_cors_origins="*",
            trusted_hosts="crm.aastha.test",
        )


def test_valid_production_settings_are_accepted():
    settings = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret="z" * 64,
        database_url="postgresql+psycopg://aastha:verystrongpassword@db:5432/aastha",
        api_cors_origins="https://crm.aastha.test",
        trusted_hosts="crm.aastha.test",
        api_docs_enabled=False,
    )
    assert settings.is_production is True
    assert settings.api_docs_enabled is False


def test_production_compose_keeps_database_internal_and_no_dev_seed():
    compose = (ROOT / "docker-compose.prod.yml").read_text()
    db_block = compose.split("  db:", 1)[1].split("\n  api:", 1)[0]
    assert "ports:" not in db_block
    api_block = compose.split("  api:", 1)[1].split("\n  web:", 1)[0]
    assert "python -m app.seed" not in api_block
    assert "--reload" not in compose
    assert "  bootstrap:" in compose
    assert "Dockerfile.prod" in compose


def test_production_containers_drop_root_and_web_builds_release():
    api_docker = (ROOT / "apps/api/Dockerfile.prod").read_text()
    web_docker = (ROOT / "apps/web/Dockerfile.prod").read_text()
    assert "USER aastha" in api_docker
    assert "USER aastha" in web_docker
    assert "npm run build" in web_docker
    assert 'npm", "run", "start' in web_docker


def test_login_page_does_not_ship_seeded_passwords():
    login = (ROOT / "apps/web/app/login/page.tsx").read_text()
    for secret in ["Reception123!", "SuperReception123!", "ClinicAdmin123!", "ChangeMe123!", "Doctor123!"]:
        assert secret not in login
    assert 'useState("")' in login


def test_branch_and_role_expiry_guards_are_wired():
    permissions = (ROOT / "apps/api/app/core/permissions.py").read_text()
    access = (ROOT / "apps/api/app/core/access.py").read_text()
    appointments = (ROOT / "apps/api/app/api/routes/appointments.py").read_text()
    visits = (ROOT / "apps/api/app/api/routes/visits.py").read_text()
    finance = (ROOT / "apps/api/app/api/routes/finance.py").read_text()
    assert "UserRole.valid_until" in permissions and "UserRole.valid_from" in permissions
    assert "def ensure_branch_access" in access
    assert "ensure_branch_access" in appointments
    assert "ensure_branch_access" in visits
    assert "ensure_branch_access" in finance
    assert "Bill Patient must match Visit Patient" in finance


def test_preflight_accepts_strong_local_production_env(tmp_path):
    env = tmp_path / ".env.production"
    env.write_text(textwrap.dedent("""
        POSTGRES_DB=aastha
        POSTGRES_USER=aastha
        POSTGRES_PASSWORD=VeryStrongDbPassword123456789
        DATABASE_URL=postgresql+psycopg://aastha:VeryStrongDbPassword123456789@db:5432/aastha
        JWT_SECRET=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ
        API_CORS_ORIGINS=https://crm.aastha.test
        TRUSTED_HOSTS=crm.aastha.test,localhost
        API_DOCS_ENABLED=false
    """).strip() + "\n")
    env.chmod(0o600)
    result = subprocess.run(
        ["python", "scripts/preflight.py", "--env-file", str(env)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Preflight PASSED" in result.stdout
