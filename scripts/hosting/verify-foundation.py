"""Check RB-10 controls in a disposable local K3s Docker container only."""

import argparse
import json
import subprocess

IMAGE = "busybox:1.37.0@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e"
LABEL = {"roombook.test": "rb10"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="roombook-rb10-validation")
    args = parser.parse_args()
    if not args.container.startswith("roombook-rb10-validation"):
        parser.error("Use a named disposable RB-10 validation container.")

    def kubectl(*command, payload=None, required=True):
        result = subprocess.run(
            ["docker", "exec", "-i", args.container, "kubectl", *command],
            check=False,
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if required and result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result

    def apply(obj):
        return kubectl("apply", "-f", "-", payload=obj)

    def pod(namespace, name):
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name, "namespace": namespace, "labels": LABEL},
            "spec": {
                "automountServiceAccountToken": False,
                "restartPolicy": "Never",
                "securityContext": {
                    "runAsNonRoot": True,
                    "runAsUser": 1000,
                    "seccompProfile": {"type": "RuntimeDefault"},
                },
                "containers": [
                    {
                        "name": "probe",
                        "image": IMAGE,
                        "command": [
                            "sh",
                            "-c",
                            "mkdir -p /tmp/www; echo rb10-ok > /tmp/www/index.html; exec httpd -f -p 8080 -h /tmp/www",
                        ],
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "readOnlyRootFilesystem": True,
                            "capabilities": {"drop": ["ALL"]},
                        },
                        "resources": {
                            "requests": {"cpu": "10m", "memory": "16Mi"},
                            "limits": {"cpu": "50m", "memory": "32Mi"},
                        },
                        "volumeMounts": [{"name": "scratch", "mountPath": "/tmp"}],
                    }
                ],
                "volumes": [{"name": "scratch", "emptyDir": {"sizeLimit": "1Mi"}}],
            },
        }

    namespaces = [
        "roombook-prod",
        "roombook-staging",
        "roombook-monitoring",
        "roombook-edge",
    ]
    results = []
    for ns in namespaces:
        sa = json.loads(kubectl("get", "sa", "default", "-n", ns, "-o", "json").stdout)
        assert sa.get("automountServiceAccountToken") is False
        results.append(f"PASS {ns}: default service-account token automount disabled")

    try:
        for ns, name in [
            ("roombook-prod", "rb10-server"),
            ("roombook-staging", "rb10-client"),
        ]:
            apply(pod(ns, name))
            kubectl(
                "wait",
                "pod/" + name,
                "-n",
                ns,
                "--for=condition=Ready",
                "--timeout=150s",
            )
        server = json.loads(
            kubectl(
                "get", "pod", "rb10-server", "-n", "roombook-prod", "-o", "json"
            ).stdout
        )
        address = server["status"]["podIP"]

        def client(*command, required=True):
            return kubectl(
                "exec",
                "-n",
                "roombook-staging",
                "rb10-client",
                "--",
                *command,
                required=required,
            )

        client("nslookup", "kubernetes.default.svc.cluster.local")
        results.append("PASS cluster DNS resolves under default-deny")
        client(
            "sh", "-c", "test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token"
        )
        results.append("PASS test pod has no Kubernetes API token")
        assert (
            client(
                "wget", "-T", "3", "-qO-", f"http://{address}:8080", required=False
            ).returncode
            != 0
        )
        results.append("PASS Staging to Production HTTP blocked by default")

        for ns, other, direction, endpoint in [
            ("roombook-staging", "roombook-prod", "Egress", "to"),
            ("roombook-prod", "roombook-staging", "Ingress", "from"),
        ]:
            apply(
                {
                    "apiVersion": "networking.k8s.io/v1",
                    "kind": "NetworkPolicy",
                    "metadata": {
                        "name": "rb10-test-allow",
                        "namespace": ns,
                        "labels": LABEL,
                    },
                    "spec": {
                        "podSelector": {"matchLabels": LABEL},
                        "policyTypes": [direction],
                        direction.lower(): [
                            {
                                endpoint: [
                                    {
                                        "namespaceSelector": {
                                            "matchLabels": {
                                                "kubernetes.io/metadata.name": other
                                            }
                                        },
                                        "podSelector": {"matchLabels": LABEL},
                                    }
                                ],
                                "ports": [{"protocol": "TCP", "port": 8080}],
                            }
                        ],
                    },
                }
            )
        # Retry briefly for network-policy reconciliation, not application readiness.
        allowed = client(
            "sh",
            "-c",
            f"for attempt in 1 2 3 4 5; do wget -T 2 -qO- http://{address}:8080 && exit 0; sleep 1; done; exit 1",
        )
        assert "rb10-ok" in allowed.stdout
        results.append(
            "PASS explicit permissions at both ends enable the control request"
        )

        invalid = pod("roombook-prod", "rb10-insecure")
        invalid["spec"]["containers"][0]["securityContext"]["privileged"] = True
        invalid["spec"]["containers"][0]["securityContext"][
            "allowPrivilegeEscalation"
        ] = True
        rejected = kubectl("apply", "-f", "-", payload=invalid, required=False)
        assert rejected.returncode and "PodSecurity" in rejected.stderr, (
            rejected.stdout + rejected.stderr
        )
        results.append("PASS restricted pod security rejects privileged Production pod")

        oversized = pod("roombook-staging", "rb10-over-budget")
        oversized["spec"]["containers"][0]["resources"]["limits"]["memory"] = "1100Mi"
        rejected = kubectl("apply", "-f", "-", payload=oversized, required=False)
        assert rejected.returncode and "exceeded quota" in rejected.stderr, (
            rejected.stdout + rejected.stderr
        )
        results.append("PASS Staging memory quota rejects an over-budget pod")
        encryption = subprocess.run(
            ["docker", "exec", args.container, "k3s", "secrets-encrypt", "status"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "Encryption Status: Enabled" in encryption.stdout
        results.append("PASS K3s secrets encryption enabled in the disposable cluster")
        print("\n".join(results))
    finally:
        for ns in namespaces:
            kubectl(
                "delete",
                "pod,networkpolicy",
                "-n",
                ns,
                "-l",
                "roombook.test=rb10",
                "--ignore-not-found",
                "--wait=false",
                required=False,
            )


if __name__ == "__main__":
    main()
