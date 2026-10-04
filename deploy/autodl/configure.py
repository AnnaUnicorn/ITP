"""Prepare the AutoDL production configuration without printing provider secrets."""

import argparse
import os
import secrets
import subprocess
from pathlib import Path

from itp.config import Settings
from itp.provider_settings import save_provider_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    args = parser.parse_args()
    app_dir = Path("/root/autodl-tmp/itp-app")
    data_dir = Path("/root/autodl-tmp/itp-data")
    env_file = app_dir / ".env"
    data_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(data_dir, 0o700)

    # These services are intentionally inactive for this deployment. In particular,
    # the copied FaceVerse token was a FLUX token, not a valid FaceVerse credential.
    save_provider_settings(env_file, {
        "flux_klein_endpoint": "",
        "flux_klein_api_key": "",
        "faceverse_endpoint": "",
        "faceverse_api_key": "",
    })
    content = env_file.read_text(encoding="utf-8")
    names = {"ITP_PUBLIC_ORIGIN", "ITP_DATA_DIR", "ITP_SEGMENTATION_MODEL"}
    lines = [line for line in content.splitlines() if line.split("=", 1)[0].strip() not in names]
    lines.extend([
        f"ITP_PUBLIC_ORIGIN={args.origin}",
        f"ITP_DATA_DIR={data_dir}",
        f"ITP_SEGMENTATION_MODEL={app_dir / 'models/u2netp.onnx'}",
    ])
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(env_file, 0o600)
    # Fail before opening a public listener if required provider configuration is absent.
    settings = Settings(_env_file=env_file)
    if not (settings.geometry_ready and settings.tryon_ready and settings.pose_ready):
        raise SystemExit("Core provider configuration is incomplete")

    password_file = data_dir / "access-password"
    if not password_file.exists():
        password_file.write_text(secrets.token_urlsafe(24) + "\n", encoding="utf-8")
        os.chmod(password_file, 0o600)
    password = password_file.read_text(encoding="utf-8").strip()
    subprocess.run(
        ["htpasswd", "-i", "-cB", "/etc/nginx/itp.htpasswd", "itp"],
        input=password + "\n", text=True, check=True, stdout=subprocess.DEVNULL,
    )
    os.chown("/etc/nginx/itp.htpasswd", 0, 33)  # Ubuntu's www-data group
    os.chmod("/etc/nginx/itp.htpasswd", 0o640)
    # The previous FLUX token was exposed in a chat transcript; invalidate it.
    flux_token = Path("/root/autodl-tmp/itp-flux-klein-service/.token")
    if flux_token.is_file():
        flux_token.write_text(secrets.token_urlsafe(32) + "\n", encoding="utf-8")
        os.chmod(flux_token, 0o600)
    print("Production configuration validated; credentials stored on server")


if __name__ == "__main__":
    main()
