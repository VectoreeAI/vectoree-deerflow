"""Regression tests for the GitLab remote deploy contract.

The remote stack publishes ``127.0.0.1:5174`` because vectoree-starter already
owns ``5173`` on the same host. Local compose files stay on ``2026``.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_COMPOSE = REPO_ROOT / "docker-compose.deploy.yml"
REMOTE_SCRIPT = REPO_ROOT / "deploy" / "deploy-remote.sh"
ENV_EXAMPLE = REPO_ROOT / "deploy" / "env.example"
GITLAB_CI = REPO_ROOT / ".gitlab-ci.yml"

NGINX_PORT = "127.0.0.1:${DEERFLOW_WEB_PORT:-5174}:2026"
CALLBACK_PORT = "127.0.0.1:53682:53682"


def _compose() -> dict:
    return yaml.safe_load(DEPLOY_COMPOSE.read_text(encoding="utf-8"))


def test_deploy_compose_publishes_starter_port_plus_one():
    compose = _compose()
    services = compose["services"]

    assert compose["name"] == "vectoree-deerflow"
    assert set(services) == {"redis", "gateway", "frontend", "nginx"}
    assert services["nginx"]["image"] == "nginx:alpine"
    assert services["redis"]["image"] == "redis:7-alpine"
    assert services["nginx"]["ports"] == [NGINX_PORT]
    assert services["frontend"]["ports"] == [CALLBACK_PORT]
    assert "DEPLOY_MODE=${DEPLOY_MODE:-local}" in services["frontend"]["environment"]
    assert "ports" not in services["gateway"]
    assert "ports" not in services["redis"]
    for name, service in services.items():
        assert "build" not in service, name

    text = DEPLOY_COMPOSE.read_text(encoding="utf-8")
    assert "docker.sock" not in text
    assert "provisioner" not in services


def test_remote_script_pulls_without_building_or_dropping_volumes():
    script = REMOTE_SCRIPT.read_text(encoding="utf-8")

    assert "dc up -d --remove-orphans --no-build" in script
    assert 'export DEERFLOW_WEB_PORT="${DEERFLOW_WEB_PORT:-5174}"' in script
    assert 'export DEPLOY_MODE="${DEPLOY_MODE:-local}"' in script
    assert "DEPLOY_MODE must be local or cloud" in script
    assert 'curl -fsS "http://127.0.0.1:${DEERFLOW_WEB_PORT}/health"' in script
    assert "dc logs --tail=80 gateway nginx" in script
    assert "down -v" not in script
    assert "--volumes" not in script
    assert "docker build" not in script


def test_env_example_defaults_web_port_to_5174():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "DEERFLOW_WEB_PORT=5174" in text
    assert "DEPLOY_MODE=cloud" in text
    assert "VECTOREE_IMAGE_MODEL=bytedance-seed/seedream-5-0-pro" in text
    assert "VECTOREE_VIDEO_MODEL=alibaba/wan-3.0" in text
    assert "VECTOREE_SPEECH_MODEL=sesame/csm-1b" in text
    assert "DEERFLOW_GATEWAY_IMAGE=" in text
    assert "DEERFLOW_FRONTEND_IMAGE=" in text
    assert "BETTER_AUTH_SECRET=" in text
    assert "DEER_FLOW_INTERNAL_AUTH_TOKEN=" in text


def test_remote_script_adds_new_template_keys_without_overwriting(tmp_path):
    import subprocess

    script = REMOTE_SCRIPT.read_text(encoding="utf-8")
    start = script.index("merge_new_defaults() {")
    end = script.index("\n}\n", start) + 3
    (tmp_path / "template").write_text("# note\nKEEP=template\nNEW_KEY=default\nEMPTY=\n", encoding="utf-8")
    (tmp_path / ".env").write_text("KEEP=mine\n", encoding="utf-8")

    subprocess.run(
        ["bash", "-c", script[start:end] + "\nmerge_new_defaults template"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    assert (tmp_path / ".env").read_text(encoding="utf-8") == "KEEP=mine\nNEW_KEY=default\nEMPTY=\n"
    assert script.index("merge_new_defaults deploy/env.example") < script.index("ensure_secret BETTER_AUTH_SECRET")


def test_gitlab_ci_deploys_dev_and_main_in_cloud_mode():
    ci = yaml.safe_load(GITLAB_CI.read_text(encoding="utf-8"))
    deploy_script = "\n".join(ci[".deploy"]["script"])

    assert ci["deploy_development"]["rules"] == [{"if": '$CI_COMMIT_BRANCH == "dev"'}]
    assert ci["deploy_production"]["rules"] == [{"if": '$CI_COMMIT_BRANCH == "main"'}]
    assert ci["deploy_production"]["needs"] == ["test", "backup_main"]
    assert ci["deploy_development"]["variables"]["DEERFLOW_GATEWAY_IMAGE"].endswith("/gateway:dev")
    assert "DEPLOY_MODE=cloud" in deploy_script
    assert 'sudo -E bash "$DEPLOY_PATH/deploy/deploy-remote.sh"' in deploy_script
    for shipped in ("docker-compose.deploy.yml", "deploy/deploy-remote.sh", "deploy/env.example", "docker/nginx/nginx.conf", "skills/public"):
        assert shipped in deploy_script
    assert "skills/custom" not in deploy_script.split("tar czf", 1)[1].split("|", 1)[0]


def test_cloud_site_is_built_and_deployed_under_deerflow():
    ci = yaml.safe_load(GITLAB_CI.read_text(encoding="utf-8"))
    deploy_script = "\n".join(ci[".deploy"]["script"])
    script = REMOTE_SCRIPT.read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")

    assert ci["variables"]["DEERFLOW_PUBLIC_BASE_PATH"] == "/deerflow"
    assert '--build-arg NEXT_PUBLIC_BASE_PATH="$DEERFLOW_PUBLIC_BASE_PATH"' in deploy_script
    assert "DEERFLOW_PUBLIC_BASE_PATH='${DEERFLOW_PUBLIC_BASE_PATH}'" in deploy_script
    assert 'DEER_FLOW_PUBLIC_BASE_PATH="$DEERFLOW_PUBLIC_BASE_PATH"' in deploy_script
    assert 'upsert_env DEER_FLOW_PUBLIC_BASE_PATH "$IN_PUBLIC_BASE_PATH"' in script
    assert "DEER_FLOW_PUBLIC_BASE_PATH=/deerflow" in ENV_EXAMPLE.read_text(encoding="utf-8")
    builder, prod = dockerfile.split("AS prod", 1)
    for stage in (builder, prod):
        assert 'ARG NEXT_PUBLIC_BASE_PATH=""' in stage
        assert "ENV NEXT_PUBLIC_BASE_PATH=$NEXT_PUBLIC_BASE_PATH" in stage
    assert builder.index("ENV NEXT_PUBLIC_BASE_PATH") < builder.index("pnpm build")


def test_remote_script_writes_the_public_base_path_each_deploy(tmp_path):
    import subprocess

    script = REMOTE_SCRIPT.read_text(encoding="utf-8")
    start = script.index("upsert_env() {")
    end = script.index("\n}\n", start) + 3
    block_start = script.index('if [[ -n "$IN_PUBLIC_BASE_PATH" ]]; then')
    block_end = script.index("fi\n", block_start) + 3
    (tmp_path / ".env").write_text("DEER_FLOW_PUBLIC_BASE_PATH=/old\nKEEP=1\n", encoding="utf-8")

    subprocess.run(
        ["bash", "-c", script[start:end] + '\nIN_PUBLIC_BASE_PATH="/deerflow"\n' + script[block_start:block_end]],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    assert (tmp_path / ".env").read_text(encoding="utf-8") == "KEEP=1\nDEER_FLOW_PUBLIC_BASE_PATH=/deerflow\n"


def test_gitlab_ci_checks_backs_up_and_publishes():
    ci = yaml.safe_load(GITLAB_CI.read_text(encoding="utf-8"))
    text = GITLAB_CI.read_text(encoding="utf-8")
    workflow = [rule["if"] for rule in ci["workflow"]["rules"]]
    test_rules = [rule["if"] for rule in ci["test"]["rules"]]
    test_script = "\n".join(ci["test"]["script"])
    backup_script = "\n".join(ci["backup_main"]["script"])
    publish_script = "\n".join(ci["publish_github"]["script"])
    auth_script = "\n".join(ci[".git_auth"]["before_script"])
    github_url = "https://x-access-token:${GITHUB_TOKEN}@github.com/VectoreeAI/vectoree-deerflow.git"

    assert ci["stages"] == [".pre", "check", "deploy", "publish"]
    assert '$CI_PIPELINE_SOURCE == "merge_request_event"' in workflow
    assert '$CI_COMMIT_BRANCH == "dev"' in workflow
    assert '$CI_COMMIT_BRANCH == "main"' in workflow
    assert '$CI_PIPELINE_SOURCE == "web"' in workflow

    assert ci["test"]["image"] == "python:3.12-slim-bookworm"
    assert '$CI_PIPELINE_SOURCE == "merge_request_event"' in test_rules
    assert '$CI_COMMIT_BRANCH == "dev"' in test_rules
    assert '$CI_COMMIT_BRANCH == "main"' in test_rules
    assert "pytest" in test_script
    assert "backend/tests/test_gitlab_deploy_contract.py" in test_script
    assert "docker login" not in test_script
    assert "ssh " not in test_script

    assert ci["backup_main"]["extends"] == ".git_auth"
    assert ci["backup_main"]["stage"] == ".pre"
    assert ci["backup_main"]["resource_group"] == "deerflow-main-backup"
    assert ci["backup_main"]["rules"] == [{"if": '$CI_COMMIT_BRANCH == "main"'}]
    assert "0000000000000000000000000000000000000000" in backup_script
    assert "chore: backup main before release" in backup_script
    assert backup_script.index("exit 0") < backup_script.index("git merge")

    assert ci["publish_github"]["extends"] == ".git_auth"
    assert ci["publish_github"]["stage"] == "publish"
    assert ci["publish_github"]["needs"] == ["test", "backup_main"]
    assert ci["publish_github"]["rules"] == [{"if": '$CI_COMMIT_BRANCH == "main"'}]
    assert github_url in publish_script
    assert '--force-with-lease="refs/heads/main:${remote_sha}"' in publish_script
    assert "Refusing to overwrite." in publish_script
    assert publish_script.index("GITHUB_TOKEN") < publish_script.index("git fetch")

    assert ci[".git_auth"]["variables"]["GIT_ASKPASS"] == "/tmp/git-askpass"
    assert 'git remote set-url origin "https://${CI_SERVER_HOST}/${CI_PROJECT_PATH}.git"' in auth_script
    assert '"$GITHUB_TOKEN"' in auth_script
    assert '"$CI_JOB_TOKEN"' in auth_script
    assert "set -x" not in text
    assert "PRIVATE KEY" not in text
    assert re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text) is None
    scrubbed = text.replace(github_url, "https://github.com/VectoreeAI/vectoree-deerflow.git")
    assert re.search(r"://[^\s/]+@", scrubbed) is None
