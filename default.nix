{ pkgs ? import <nixpkgs> {} }:

pkgs.stdenv.mkDerivation {
  name = "ask-cli-3.0";
  src = ./.;

  nativeBuildInputs = [ pkgs.makeWrapper ];

  buildInputs = [
    (pkgs.python3.withPackages (ps: with ps; [ requests rich cryptography ]))
  ];

  installPhase = ''
    # 1. Setup standard directories
    mkdir -p $out/bin
    mkdir -p $out/share/ask

    # 2. Separate binary and static assets
    cp ask.py $out/bin/ask
    cp oobe.py $out/bin/oobe
    cp -r assets $out/share/ask/
    chmod +x $out/bin/ask
    chmod +x $out/bin/oobe

    # 3. Fix Python shebang for the Nix store
    patchShebangs $out/bin/ask
    patchShebangs $out/bin/oobe

    # 4. Wrap the program securely
    wrapProgram $out/bin/ask \
      --set ASK_ASSETS_DIR "$out/share/ask/assets" \
      --prefix PYTHONPATH : "$out/share/ask" \
      --prefix PATH : ${pkgs.lib.makeBinPath [
        pkgs.ddgr         # For the 'search' tool
        pkgs.lynx         # For the 'read' tool
        pkgs.bubblewrap   # For the sandboxed 'run' tool
        pkgs.coreutils    # For cut, tr, groups (identity prompt)
        pkgs.gnugrep      # For grep (identity prompt)
      ]}

    # 5. Wrap oobe (only needs python + assets path, no shell tools)
    wrapProgram $out/bin/oobe \
      --set ASK_ASSETS_DIR "$out/share/ask/assets" \
      --prefix PYTHONPATH : "$out/share/ask"
  '';
}
