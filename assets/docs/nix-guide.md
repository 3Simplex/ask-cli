# 🤖 NixOS & Nix Flakes: Operational Guidelines for AI Agents

You have direct CLI access to the user's environment. You must strictly adhere to NixOS paradigms. 

## 🛑 1. Core Directives (Never break these)
*   **The `/nix/store` is READ-ONLY.** Never attempt to `chmod`, `chown`, `sed`, or manually edit files inside the Nix store. 
*   **No FHS (Filesystem Hierarchy Standard).** Directories like `/bin`, `/usr/bin`, `/lib`, and `/usr/lib` generally do not exist or are highly restricted. Do not rely on them. Do not try to download and run arbitrary pre-compiled binaries (they will fail with "file not found" due to missing dynamic linkers).
*   **Never suggest standard package managers.** Do not run `apt`, `yum`, `pacman`, `brew`, or `pip install` globally. Everything is managed via Nix.

## ❄️ 2. Working with Flakes (The #1 Gotcha)
*   **Git Tracking is Mandatory:** Nix flakes **ignore files that are not tracked by git**. If you write a new script, patch, or `flake.nix` file, you MUST run `git add <file>` before running `nix build` or `nix run`. If you forget, Nix will claim the file doesn't exist or build a stale version.
*   **Dirty Trees:** If you modify tracked files, you don't need to commit them to build, but you *must* add them to the index (`git add`).

## 🛠 3. Tooling & Ephemeral Environments (Use Your CLI)
Because you have CLI access, use `nix` to spawn tools statelessly instead of asking the user to install them.
*   **Need a tool temporarily?** Use `nix run` or `nix shell`.
    *   *Example:* To lint a bash script: `nix run nixpkgs#shellcheck -- script.sh`
    *   *Example:* To parse JSON: `nix run nixpkgs#jq -- -r '.keys' file.json`
    *   *Example:* To use Python with a package: `nix shell nixpkgs#python311 nixpkgs#python311Packages.requests -c python3 script.py`
*   **Wrapper Scripts:** Shell scripts installed via Nix are usually wrapped (prepended with environment variables). If an error says "line 250", check the *compiled* file in the `/nix/store/.../bin/` to find the real line, then map it back to the original source.

## 📦 4. Building and Overriding Packages
*   **The FOD Hash Dance:** When overriding packages that download from the internet (e.g., `fetchNpmDeps`, `fetchCargoTarball`, `fetchFromGitHub`), Nix requires a cryptographic hash to maintain the offline sandbox.
    *   **The Trick:** If you change a source URL or a `package-lock.json`, the hash changes. Do NOT try to guess the hash.
    *   Set the hash to: `hash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";` (or `lib.fakeHash`).
    *   Run the build. It will fail.
    *   Extract the *actual* hash from the stderr (`got: sha256-xxx...`).
    *   Use `sed` or standard file editing to replace the fake hash with the real one, then build again.
*   **Optimization:** When compiling C/C++ projects, inject `-O3 -march=native` into `NIX_CFLAGS_COMPILE`. Disable Nix's default hardening if maximum bare-metal speed is required: `hardeningDisable = [ "all" ];`.

## 🔍 5. Inspecting the Environment (Commands to use)
When diagnosing issues, run these commands to gather context:
*   Find the true path of a command: `readlink -f $(which command_name)`
*   View a derivation's output paths without building: `nix eval .#default.outPath`
*   Check the active system architecture: `nix eval --expr 'builtins.currentSystem'`
*   Search for available packages: `nix search nixpkgs <name>`
*   Format a Nix file automatically: `nix run nixpkgs#nixfmt-rfc-style -- file.nix`

## 🧠 6. Agent Problem-Solving Workflow
1.  **Analyze:** What is the user trying to do? (e.g., Build a C++ project with custom flags, fix a bash script syntax error, update a system config).
2.  **Verify:** Use the CLI to read the existing `flake.nix`, `.sh` scripts, or logs.
3.  **Lint First:** If writing or fixing bash, ALWAYS run `shellcheck` via `nix run` before finalizing the change.
4.  **Edit & Track:** Use standard tools (`sed`, `cat << 'EOF'`) to update the file, followed immediately by `git add <file>`.
5.  **Build & Test:** Run `nix build .#<target>` or the user's specific build command. Read the stderr if it fails.
6.  **FOD Correction:** If a hash mismatch occurs, parse the new hash and patch the file automatically.
