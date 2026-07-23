{ pkgs ? import <nixpkgs> {} }:

pkgs.stdenv.mkDerivation {
  name = "ask-cli-3.0";
  src = ./.;

  nativeBuildInputs = [ pkgs.makeWrapper ];

  buildInputs = [
    (pkgs.python3.withPackages (ps: with ps; [ requests rich ]))
  ];

  installPhase = ''
    # 1. Setup standard directories
    mkdir -p $out/bin
    mkdir -p $out/share/ask

    # 2. Separate binary and static assets
    cp ask.py $out/bin/ask
    cp -r assets $out/share/ask/
    chmod +x $out/bin/ask

    # 3. Fix Python shebang for the Nix store
    patchShebangs $out/bin/ask

    # 4. Wrap the program securely
    wrapProgram $out/bin/ask \
      --set ASK_CONFIG_DIR "$out/share/ask/assets/config" \
      --prefix PATH : ${pkgs.lib.makeBinPath [
        pkgs.ddgr         # For the 'search' tool
        pkgs.lynx         # For the 'read' tool
        pkgs.bubblewrap   # For the sandboxed 'run' tool
        pkgs.coreutils    # For cut, tr, groups (identity prompt)
        pkgs.gnugrep      # For grep (identity prompt)
      ]}
  '';
}
