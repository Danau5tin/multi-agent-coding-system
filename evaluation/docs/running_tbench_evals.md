This doc shows how to setup a GPU node and run the evals (tested with 8xH100 bare metal node from [hyperbolic](https://app.hyperbolic.ai/) - should work with VM instances too and other providers).

1. Install docker, exit node, and re-enter
```bash
echo "Updating package index..."
sudo apt-get update -y

# Install prerequisites
echo "Installing prerequisites..."
sudo apt-get install -y ca-certificates curl gnupg lsb-release

# Add Docker's official GPG key
echo "Adding Docker GPG key..."
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Set up repository
echo "Setting up Docker repository..."
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
echo "Installing Docker Engine..."
sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add current user to docker group
echo "Adding $USER to docker group..."
sudo usermod -aG docker $USER

# This configuration creates much smaller subnets (size /24),
# which dramatically increases the number of available networks from ~31 to over 500.
# This prevents the 'all predefined address pools have been fully subnetted' error.
echo "Configuring Docker daemon for a high number of networks..."
sudo mkdir -p /etc/docker
cat <<EOF | sudo tee /etc/docker/daemon.json
{
  "default-address-pools": [
    {"base": "172.17.0.0/16", "size": 24},
    {"base": "192.168.0.0/16", "size": 24}
  ],
  "max-concurrent-downloads": 10,
  "max-concurrent-uploads": 10
}
EOF

echo "Restarting and enabling Docker service to apply new configuration..."
sudo systemctl restart docker
sudo systemctl enable docker

echo ""
echo "Docker installation and configuration complete!"
echo "IMPORTANT: Please log out and back in for the group changes to take effect."
```
Exit the ssh connection and re-connect

2. Uv install & Clone repo and cd into it & switch to relevant branch if required
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

ulimit -n 1048576
cd ~
git clone https://github.com/Danau5tin/multi-agent-coding-system.git
cd multi-agent-coding-system
uv sync
```

3. Start tmux session
```bash
sudo apt-get update && sudo apt-get install -y tmux
tmux new -s evals
```

4. If not using APIs, and running models on GPUS, [see here](./deploying_model_examples.md) for deployment examples with SGLang and vLLM

5. Export env vars
```bash
export ORCA_ORCHESTRATOR_MODEL=""
export ORCA_SUBAGENT_MODEL=""
# Also include API_BASE & API_KEY specifics if using different inference options for Orca & Subagents
export N_CONCURRENT_TRIALS=25 # Alter based on CPU power
export N_ATTEMPTS=5 # TBench requires 5 attempts per task for submission
```
See [the script](../../evaluation/run_terminal_bench_eval.sh) for all env vars

**IF RUNNING ON TRAIN DS**
In order for the conversion script to work, we need to create an example TBench task one time so the cli can be used by the script afterwards.
```bash
mkdir tasks/
# Create an example task, this is required for the script to run successfully because tb's first start up requires user interaction
uv run tb tasks create example_task_001 \
  --name "Dan Austin" \
  --email "dan@aituning.ai" \
  --category "general" \
  --difficulty "easy" \
  --instruction "Write a Python function that calculates the factorial of a number" \
  --tag "python" \
  --tag "algorithms" \
  --expert-time-estimate-min 2 \
  --junior-time-estimate-min 2 \
  --no-interactive

# Follow the prompts. Confirm you dont want an intro and don't want to see again.

rm -rf tasks
```

6. Run evals
```bash
ulimit -n 1048576
./evaluation/run_terminal_bench_eval.sh
```