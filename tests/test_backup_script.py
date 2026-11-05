import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backup-postgres.sh"


def test_backup_script_writes_local_and_age_copy_and_prunes_old_files(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    local_dir = tmp_path / "local"
    offsite_dir = tmp_path / "offsite"
    bin_dir.mkdir()
    local_dir.mkdir()
    offsite_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text("#!/bin/sh\nprintf 'postgres dump fixture\\n'\n")
    age = bin_dir / "age"
    age.write_text(
        "#!/bin/sh\n"
        '[ "$1" = --encrypt ] || exit 2\n'
        '[ "$2" = --recipient ] || exit 2\n'
        '[ "$4" = --output ] || exit 2\n'
        'cp -- "$6" "$5"\n'
    )
    docker.chmod(0o700)
    age.chmod(0o700)
    old_local = local_dir / "mes-old.dump"
    old_offsite = offsite_dir / "mes-old.dump.age"
    old_local.write_text("old")
    old_offsite.write_text("old")
    old_time = (datetime.now(UTC) - timedelta(days=16)).timestamp()
    os.utime(old_local, (old_time, old_time))
    os.utime(old_offsite, (old_time, old_time))
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "BACKUP_DIR": str(local_dir),
        "OFFSITE_BACKUP_DIR": str(offsite_dir),
        "AGE_RECIPIENT": "age1-test-recipient",
    }

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    local_backups = list(local_dir.glob("mes-*.dump"))
    offsite_backups = list(offsite_dir.glob("mes-*.dump.age"))
    assert len(local_backups) == len(offsite_backups) == 1
    assert local_backups[0].read_text() == "postgres dump fixture\n"
    assert offsite_backups[0].read_bytes() == local_backups[0].read_bytes()
    assert local_backups[0].stat().st_mode & 0o777 == 0o600
    assert old_local.exists() is False
    assert old_offsite.exists() is False
    assert "age1-test-recipient" not in result.stdout


def test_backup_script_rejects_identical_local_and_offsite_directories(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text("#!/bin/sh\nexit 9\n")
    docker.chmod(0o700)
    age = bin_dir / "age"
    age.write_text("#!/bin/sh\nexit 9\n")
    age.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "BACKUP_DIR": str(tmp_path),
        "OFFSITE_BACKUP_DIR": str(tmp_path),
        "AGE_RECIPIENT": "age1-test-recipient",
    }

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode != 0
    assert "different directories" in result.stderr
