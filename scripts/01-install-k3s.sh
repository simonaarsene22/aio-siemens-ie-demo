#!/bin/bash
# ============================================================
# Step 1: Install K3s
# Run inside WSL2 (Ubuntu 22.04+) or a Linux VM.
# ============================================================
set -euo pipefail

echo "=== Applying kernel settings required by AIO ==="
echo fs.inotify.max_user_instances=8192 | sudo tee -a /etc/sysctl.conf
echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
echo fs.file-max=100000 | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

echo "=== Installing K3s (Traefik disabled) ==="
curl -sfL https://get.k3s.io | sh -s - \
  --disable traefik \
  --write-kubeconfig-mode 644

sudo systemctl enable k3s
sleep 10

echo "=== Setting up kubeconfig ==="
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown "$(id -u):$(id -g)" ~/.kube/config
chmod 0600 ~/.kube/config

if ! grep -q "KUBECONFIG" ~/.bashrc; then
  echo 'export KUBECONFIG=~/.kube/config' >> ~/.bashrc
fi
export KUBECONFIG=~/.kube/config

echo "=== K3s ready ==="
kubectl get nodes
