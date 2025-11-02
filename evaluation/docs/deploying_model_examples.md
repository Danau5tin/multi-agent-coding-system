**SGLang across 8 GPUS**

[Quickstart](https://docs.sglang.ai/get_started/install.html)

```bash
uv venv && \
uv pip install "sglang[all]>=0.5.2" && \
uv pip install accelerate && \
uv run python -m sglang.launch_server \
--model-path Qwen/Qwen3-Coder-30B-A3B-Instruct \
--tp 8 \
--ep-size 8 \
--host 0.0.0.0 \
--context-length 58000
```
The subagent env vars would be:
```bash
export ORCA_SUBAGENT_MODEL="openai/Qwen/Qwen3-Coder-30B-A3B-Instruct"
export ORCA_SUBAGENT_API_BASE="http://127.0.0.1:30000/v1"
export ORCA_SUBAGENT_API_KEY="placeholder"
```

**vLLM across 8 GPUs**

[Quickstart](https://docs.vllm.ai/en/latest/getting_started/quickstart.html#installation)

```bash
uv venv --python 3.12 --seed
source .venv/bin/activate
uv pip install vllm==0.10.2 --torch-backend=auto 

vllm serve Danau5tin/Orca-Agent-v0.1 \
--tensor-parallel-size 8
```

The env vars would be:
```bash
export ORCA_ORCHESTRATOR_MODEL="openai/Danau5tin/Orca-Agent-v0.1"
export ORCA_ORCHESTRATOR_API_BASE="http://127.0.0.1:8000/v1"
export ORCA_ORCHESTRATOR_API_KEY="placeholder"
```

You can also deploy the subagent on the same node. For example if you want to deploy the subagent on just 4/8 GPUs whilst the other 4 deploy the Orchestrator:
```bash
CUDA_VISIBLE_DEVICES=4,5,6,7 \
vllm serve Qwen/Qwen3-Coder-30B-A3B-Instruct \
--tensor-parallel-size 4 \
--port 8001

# Similar command for the first 4 GPUs using CUDA_VISIBLE_DEVICES=0,1,2,3
```

**Test**
```bash
NODE_IP=127.0.0.1
PORT=8000 # or 30000 for sglang

curl -X POST http://$NODE_IP:$PORT/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3-Coder-30B-A3B-Instruct",
    "messages": [{"role": "user", "content": "Say hello world!"}]
  }'
```

**vLLM Multi-node deployment (GLM-4.6-FP8 across 2 nodes with 16 GPUs)**

[Multi-node setup guide](https://docs.vllm.ai/en/latest/serving/distributed_serving.html#multi-node-inference-and-serving)

Prerequisites:
- Download model on both nodes first to avoid timeouts during startup

**On both nodes**
```bash
export NETWORK_INTERFACE=$(ip -o addr show | grep "inet.*10\." | grep -v "127.0.0.1" | awk '{print $2}' | head -1) && \
echo "Detected network interface: $NETWORK_INTERFACE" && \
export GLOO_SOCKET_IFNAME=$NETWORK_INTERFACE && \
export NCCL_SOCKET_IFNAME=$NETWORK_INTERFACE

uv venv --python 3.12 --seed
source .venv/bin/activate
uv pip install vllm==0.10.2 --torch-backend=auto

sudo apt install -y nvidia-docker2
sudo systemctl daemon-reload
sudo systemctl restart docker

sudo chown -R $USER:$USER ~/.cache/huggingface/
hf download zai-org/GLM-4.6-FP8
```

**On main inference node**
```bash
# Start Ray cluster with proper network configuration
tmux new -s dock-inf

bash run_cluster.sh \
  vllm/vllm-openai \
  $NODE_N_IP \
  --head \
  ~/.cache/huggingface/ \
  -e VLLM_HOST_IP=$NODE_N_IP \
  -e GLOO_SOCKET_IFNAME=$NETWORK_INTERFACE \
  -e TP_SOCKET_IFNAME=$NETWORK_INTERFACE
```

**On second node**
```bash
tmux new -s dock-inf

bash run_cluster.sh \
  vllm/vllm-openai \
  $NODE_N_IP \
  --worker \
  ~/.cache/huggingface/ \
  -e VLLM_HOST_IP=$INF_NODE_N_IP \
  -e GLOO_SOCKET_IFNAME=$NETWORK_INTERFACE \
  -e TP_SOCKET_IFNAME=$NETWORK_INTERFACE
```

**On any node**
```bash
docker exec -it node /bin/bash
ray status  # Verify all nodes and GPUs are visible

# Serve the model
vllm serve zai-org/GLM-4.6-FP8 \
  --host 0.0.0.0 \
  --port 8000 \
  --tensor-parallel-size 16 \
  --distributed-executor-backend ray
```

The env vars would be:
```bash
export ORCA_SUBAGENT_MODEL="openai/zai-org/GLM-4.6-FP8"
export ORCA_SUBAGENT_API_BASE="http://$NODE_N_IP:8000/v1"
export ORCA_SUBAGENT_API_KEY="placeholder"
```