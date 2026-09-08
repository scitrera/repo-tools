"""Compose the existing artifact generators into releases scoped to one project."""

from __future__ import annotations

from dataclasses import replace
import re

import yaml

from ..version_sync.config import DependencyMappings
from ..version_sync.discovery import manifests_for_language


class _WorkflowDumper(yaml.SafeDumper):
    pass


def _string(dumper, value):
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|" if "\n" in value else None)


_WorkflowDumper.add_representer(str, _string)


def render_independent_releases(config):
    # Imported here to keep templates' public entry points free of a cycle.
    from .templates import (
        GENERATED_HEADER, _verify_tag_job, _go_module_tag_problems, _go_modules, build_build_docker,
        build_publish_go, build_publish_python, build_publish_npm,
    )

    problems = _go_module_tag_problems(_go_modules(config))
    if problems:
        raise ValueError("independent release: " + "; ".join(problems))
    manifests = {}
    for lang in ("go", "python", "typescript"):
        for project, manifest in manifests_for_language(config, lang).items():
            if project in manifests:
                raise ValueError(f"independent release: {project} must identify one language manifest")
            manifests[project] = (lang, manifest)
    for name, image in config.docker.images.items():
        if image.version_from not in manifests:
            raise ValueError(f"docker.images.{name}: independent releases require version_from naming a declared project")
    out = {}
    prefixes = set()
    for project, (lang, manifest) in sorted(manifests.items()):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", project):
            raise ValueError(f"independent release: unsafe workflow name {project!r}")
        if project not in config.project_versions:
            raise ValueError(f"independent release: no version declared for {project}")
        if lang == "python" and config.ci.python.publish_projects and project not in config.ci.python.publish_projects:
            continue
        if lang == "typescript" and config.ci.npm.publish_projects and project not in config.ci.npm.publish_projects:
            continue
        directory = manifest.parent.relative_to(config.root).as_posix()
        prefix = "" if directory == "." else directory + "/"
        if not re.fullmatch(r"[A-Za-z0-9_./-]*", prefix):
            raise ValueError(f"independent release: unsafe tag prefix {prefix!r}")
        if prefix in prefixes:
            raise ValueError(f"independent release: duplicate tag prefix {prefix!r}")
        prefixes.add(prefix)
        images = {k: v for k, v in config.docker.images.items() if v.version_from == project}
        for name, image in images.items():
            if image.needs and image.needs not in images:
                raise ValueError(f"docker.images.{name}: independent releases cannot cascade across projects; use an explicit versioned base_image")
        ci = replace(
            config.ci,
            go=replace(config.ci.go, module_tags="none", verify_tag_version=project if lang == "go" else None,
                       binaries=tuple(b for b in config.ci.go.binaries if b.project == project or (b.project is None and lang == "go" and len(manifests_for_language(config, "go")) == 1))),
            python=replace(config.ci.python, publish_projects=(), test_projects=(), verify_tag_version=project if lang == "python" else None),
            npm=replace(config.ci.npm, publish_projects=(), test_projects=()),
            docker=replace(config.ci.docker, enable_workflow_dispatch_version=False),
        )
        selected = replace(config, ci=ci, project_rules={project: config.project_rules[project]},
                           dependency_mappings=DependencyMappings(), docker=replace(config.docker, images=images))
        generator = {"go": build_publish_go, "python": build_publish_python, "typescript": build_publish_npm}[lang]
        rendered = generator(selected, ci)
        artifact = yaml.safe_load(rendered) if rendered else {"jobs": {}}
        jobs = artifact["jobs"]
        # A library without release attachments still gets the version gate and tests.
        if not jobs:
            from .templates import _reusable_test_jobs
            _, tests = _reusable_test_jobs(selected, ci, lang)
            jobs.update(yaml.safe_load(tests) or {})
        jobs.update(yaml.safe_load(_verify_tag_job(project, ci, tag_prefix=prefix)))
        if images:
            docker = yaml.safe_load(build_build_docker(selected, ci))
            for key, value in docker["jobs"].items():
                if key in jobs and jobs[key] != value:
                    raise ValueError(f"independent release: conflicting generated job {key}")
                jobs[key] = value
        for key, job in jobs.items():
            if key == "verify-tag":
                continue
            needs = job.get("needs", [])
            if isinstance(needs, str):
                needs = [needs]
            job["needs"] = list(dict.fromkeys(["verify-tag", *needs]))
        if "github-release" in jobs and images:
            jobs["github-release"]["needs"] = list(dict.fromkeys([*jobs["github-release"].get("needs", []), *[key for key in jobs if key.startswith(("build-", "merge-"))]]))
        workflow = {
            "name": f"Release ({project})",
            "on": {"push": {"tags": [prefix + "v*.*.*"]}},
            "concurrency": {"group": "release-${{ github.ref }}", "cancel-in-progress": False},
            "permissions": {"contents": "read", "packages": "write", "id-token": "write"},
            "jobs": jobs,
        }
        out[f"release-{project}.yml"] = GENERATED_HEADER + "\n" + yaml.dump(workflow, Dumper=_WorkflowDumper, sort_keys=False, width=120)
    return out
