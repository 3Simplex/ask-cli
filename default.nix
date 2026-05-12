{ pkgs ? import <nixpkgs> {} }:

pkgs.stdenv.mkDerivation {
  name = "ask-cli-3.0";
  src = ./.;

  buildInputs =[
    (pkgs.python3.withPackages (ps: with ps; [ requests rich ]))
  ];

  nativeBuildInputs = [ pkgs.makeWrapper ];

  installPhase = ''
    mkdir -p $out/bin $out/lib/python3.12/site-packages/ask
    cp ask.py $out/bin/ask
    cp -r ask/* $out/lib/python3.12/site-packages/ask/
    chmod +x $out/bin/ask
    
    # Add the site-packages to PYTHONPATH
    makeWrapper $out/bin/ask $out/bin/ask-wrapped \
      --prefix PYTHONPATH : $out/lib/python3.12/site-packages

    mv $out/bin/ask-wrapped $out/bin/ask

    # This fixes the #!/usr/bin/env python3 shebang to use the Nix store Python
    patchShebangs $out/bin/ask
    
    # This securely wraps the binary so it always has access to its tools
    wrapProgram $out/bin/ask \
      --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.glow pkgs.ddgr pkgs.lynx pkgs.less pkgs.bubblewrap ]}
  '';
}
