# Local development VM

Ansible provisions an Ubuntu 24.04 VM with **16 vCPUs**, **32 GiB RAM**, and an **80 GiB virtual disk**. It also prepares the guest for later application deployment with Python, Git, and Podman. The application services themselves are not deployed yet because this repository currently contains only design documents and infrastructure automation.

## Host requirements

- QEMU (`qemu-system-x86_64` and `qemu-img`), `cloud-localds`, OpenSSH, and Ansible Core.
- At least 32 GiB of available host memory and enough free disk space for the virtual disk's actual contents.
- Access to the Ubuntu 24.04 cloud image URL on the first run.
- KVM for practical performance. If `/dev/kvm` is unavailable, the playbook uses QEMU software emulation, which can boot much more slowly.

The VM state, disk, seed image, and SSH key are stored in `.local/dev-vm/`, which is ignored by Git. The guest's SSH port is forwarded to `127.0.0.1:2222`; it is not exposed on other host interfaces.

## Provision and configure

From the repository root:

```sh
ansible-playbook ansible/playbooks/dev-vm.yml
ansible-playbook ansible/playbooks/deploy.yml
```

The first playbook downloads the cloud image, creates an independent QCOW2 disk, injects a dedicated SSH public key with cloud-init, starts QEMU, and waits for SSH. The second playbook installs guest prerequisites and creates `/opt/storage-lab`. Re-running either playbook should preserve the existing VM disk and guest data.

Connect directly when needed:

```sh
ssh -i .local/dev-vm/id_ed25519 -p 2222 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=.local/dev-vm/known_hosts lab@127.0.0.1
```

To stop the VM, send a termination signal to the PID in `.local/dev-vm/qemu.pid`. Re-run the first playbook to start it again. Changing cloud-init data after first boot requires a fresh VM disk because cloud-init uses a fixed instance ID for this development VM.

The Ansible inventory is specific to this local VM. Later environments should use their own inventory and secrets mechanism while reusing deployment playbooks where appropriate.
