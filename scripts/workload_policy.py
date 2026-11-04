"""EKS keeps chart defaults; local must not reserve compute or autoscale."""

from pathlib import Path

import yaml
import re


PLATFORMS = {"eks", "local"}
UNRESERVED_PLATFORMS = {"local"}
AUTOSCALERS = {"HorizontalPodAutoscaler", "VerticalPodAutoscaler", "ScaledObject", "ScaledJob"}
# Upstream pre-delete hooks whose chart has no resources value. They run only
# when Argo CD deletes the Application, so no running workload goes unbudgeted.
UNBUDGETED_PRE_DELETE_HOOKS = {("Job", "delete-keep-secrets")}


def target_platform(target, env):
    if env.get("env"):
        return env["env"]
    return next((part for part in reversed(Path(target["appset"]).parts[:-1]) if part in PLATFORMS), "eks")


def policy_errors(manifests, platform):
    if platform == "eks":
        return production_resource_errors(manifests)
    if platform not in UNRESERVED_PLATFORMS:
        return []
    errors = []

    def inspect(value, owner, path=""):
        if isinstance(value, list):
            for index, child in enumerate(value):
                inspect(child, owner, f"{path}[{index}]")
        elif isinstance(value, dict):
            for key, child in value.items():
                location = f"{path}.{key}" if path else key
                if (key == "resources" or key.endswith("Resources")) and isinstance(child, dict):
                    for field in ("requests", "limits"):
                        quantities = child.get(field) or {}
                        if isinstance(quantities, dict) and any(name != "storage" for name in quantities):
                            errors.append(f"{owner} {location}.{field} reserves compute")
                if key in {"autoscaling", "hpa", "vpa"} and isinstance(child, dict) and child.get("enabled") is True:
                    errors.append(f"{owner} {location}.enabled must be false")
                if key == "autoscaleEnabled" and child is True:
                    errors.append(f"{owner} {location} must be false")
                inspect(child, owner, location)

    for document in yaml.safe_load_all(manifests):
        if not document or document.get("kind") == "CustomResourceDefinition":
            continue
        kind = document.get("kind")
        owner = f"{kind}/{document.get('metadata', {}).get('name', '?')}"
        if kind in AUTOSCALERS:
            errors.append(f"{owner} is not allowed on {platform}")
        if kind in {"Prometheus", "PrometheusAgent", "Alertmanager", "ThanosRuler"}:
            # Unlike core Pod APIs, monitoring CRDs reject explicit null resource maps.
            resources = document.get("spec", {}).get("resources", {})
            if not isinstance(resources, dict):
                errors.append(f"{owner} spec.resources must be an object when present")
            else:
                for field in ("requests", "limits"):
                    if field in resources and not isinstance(resources[field], dict):
                        errors.append(f"{owner} spec.resources.{field} must be an object when present")
        inspect(document, owner)
    return errors

def production_resource_errors(manifests):
    """Check Pod specs and operator resources, never arbitrary ConfigMap data."""
    errors = []

    def positive(quantity):
        if isinstance(quantity, bool):
            return False
        match = re.fullmatch(r"([+]?(?:\d+(?:\.\d*)?|\.\d+))(?:(?:[eE][+-]?\d+)|[KMGTPE]i|[numkMGTPE])?", str(quantity))
        return bool(match and float(match.group(1)) > 0)

    def budget(resources, owner, path):
        resources = resources or {}
        if not isinstance(resources, dict):
            errors.append(f"{owner} {path} must be an object")
            return
        for section, resource in (("requests", "cpu"), ("requests", "memory"), ("limits", "memory")):
            quantities = resources.get(section) or {}
            if not isinstance(quantities, dict) or not positive(quantities.get(resource)):
                errors.append(f"{owner} {path}.{section}.{resource} must reserve a positive EKS budget")

    def at(value, *keys):
        for key in keys:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value

    def pod(spec, owner, path):
        if spec is None:
            return
        if not isinstance(spec, dict):
            errors.append(f"{owner} {path} must be a Pod spec object")
            return
        for field in ("containers", "initContainers"):
            containers = spec.get(field) or []
            if not isinstance(containers, list):
                errors.append(f"{owner} {path}.{field} must be a list")
                continue
            for index, container in enumerate(containers):
                location = f"{path}.{field}[{index}]"
                if not isinstance(container, dict):
                    errors.append(f"{owner} {location} must be a container object")
                else:
                    budget(container.get("resources"), owner, location + ".resources")

    for document in yaml.safe_load_all(manifests):
        if not document or document.get("kind") == "CustomResourceDefinition":
            continue
        kind = document.get("kind")
        metadata = document.get("metadata") or {}
        owner = f"{kind}/{metadata.get('name', '?')}"
        hook = (metadata.get("annotations") or {}).get("helm.sh/hook")
        if (kind, metadata.get("name")) in UNBUDGETED_PRE_DELETE_HOOKS and hook == "pre-delete":
            continue
        if kind in {"Prometheus", "Alertmanager", "ThanosRuler"}:
            budget(at(document, "spec", "resources"), owner, "spec.resources")
            pod(document.get("spec"), owner, "spec")
        elif kind == "Pod":
            pod(document.get("spec"), owner, "spec")
        pod(at(document, "spec", "template", "spec"), owner, "spec.template.spec")
        if kind == "PodTemplate":
            pod(at(document, "template", "spec"), owner, "template.spec")
        if kind == "CronJob":
            pod(at(document, "spec", "jobTemplate", "spec", "template", "spec"), owner, "spec.jobTemplate.spec.template.spec")
        if kind in {"AnalysisTemplate", "ClusterAnalysisTemplate"}:
            for index, metric in enumerate(at(document, "spec", "metrics") or []):
                pod(at(metric, "provider", "job", "spec", "template", "spec"), owner,
                    f"spec.metrics[{index}].provider.job.spec.template.spec")
    return errors
