{ pkgs ? import <nixpkgs> {} }:

pkgs.stdenv.mkDerivation {
  name = "ask-cli-3.0";
  src = ./.;

  buildInputs =[
    (pkgs.python3.withPackages (ps: with ps; [ requests rich ]))
  ];

  nativeBuildInputs = [ pkgs.makeWrapper ];

  installPhase = ''
    mkdir -p $out/bin
    cp ask.py $out/bin/ask
    chmod +x $out/bin/ask
    
    # This fixes the #!/usr/bin/env python3 shebang to use the Nix store Python
    patchShebangs $out/bin/ask
    
    # This securely wraps the binary so it always has access to its tools
    wrapProgram $out/bin/ask \
      --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.glow pkgs.ddgr pkgs.lynx pkgs.less ]}
  '';
}
