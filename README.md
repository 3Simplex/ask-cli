# Ask-CLI: Advanced Agentic Linux Assistant 🐧

This CLI assistant leverages local LLMs to provide context-aware, powerful interaction with the Linux shell, 
moving beyond simple command execution.

## 🤖 Core Capabilities
- **Agentic Execution**: Executes shell commands () and provides descriptive feedback.
- **Information Retrieval**: Can search the web ( tool) or read remote content ( tool).
- **Context Persistence**: Supports session continuity, allowing you to pick up where you left off.
- **Routine Playbooks**: Pre-defined workflows stored as routines.

## 🛡 Security & Reliability
- **Security Watcher**: An integrated LLM-based auditor that analyzes proposed commands for malicious intent, destructive actions, or privilege escalation, providing real-time risk assessment.
- **Sandbox Mode**: Commands can be executed within a secure Bubblewrap container () for isolation.
- **Automated Approval**: Optional auto-approval feature allows immediate execution if the Security Watcher allows the command.

## ✨ Advanced Features
- **Multimodal Support**: Can accept image inputs alongside text queries.
- **Tooling**: Includes integrated tools for logging, garbage collection (), and command display ().
- **Declarative**: Designed to be highly portable, slotting easily into NixOS flakes.

---
*To start: `ask <query>` or `ask -r <routine_name>`.*
