# Ask-CLI: Advanced Agentic Linux Assistant 🐧\n\nThis CLI assistant leverages local LLMs to provide context-aware, powerful interaction with the Linux shell, 
moving beyond simple command execution.\n\n## 🤖 Core Capabilities\n- **Agentic Execution**: Executes shell commands () and provides descriptive feedback.\n- **Information Retrieval**: Can 
search the web ( tool) or read remote content ( tool).\n- **Context Persistence**: Supports session continuity, allowing you to pick up where you left off.\n- **Routine 
Playbooks**: Pre-defined workflows stored as routines.\n\n## 🛡 Security & Reliability\n- **Security Watcher**: An integrated LLM-based auditor that analyzes proposed commands for malicious 
intent, destructive actions, or privilege escalation, providing real-time risk assessment.\n- **Sandbox Mode**: Commands can be executed within a secure Bubblewrap container () for 
isolation.\n- **Automated Approval**: Optional auto-approval feature allows immediate execution if the Security Watcher clears the command.\n\n## ✨ Advanced Features\n- **Multimodal Support**: 
Can accept image inputs alongside text queries.\n- **Tooling**: Includes integrated tools for logging, garbage collection (), and command display ().\n- **Declarative**: Designed to
be highly portable, slotting easily into NixOS flakes.\n\n---\n*To start: `ask <query>` or `ask -r <routine_name>`.*
