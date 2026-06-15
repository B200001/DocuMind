#!/usr/bin/env bash
set -euo pipefail

echo "========================================="
echo "  Pulling Ollama models for documind"
echo "========================================="

# ─── LLM Model ────────────────────────────────────────────
echo ""
echo ">> Pulling LLM: llama3.1:8b ..."
ollama pull llama3.1:8b

# ─── Embedding Model ──────────────────────────────────────
echo ""
echo ">> Pulling Embed: nomic-embed-text ..."
ollama pull nomic-embed-text

echo ""
echo "✅ All models pulled successfully!"
echo "   Run 'ollama list' to verify." 