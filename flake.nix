{
  description = "Agentic NixOS Assistant - My AI Perk Card";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
      pkgsFor = system: import nixpkgs { inherit system; };
    in {
      # This defines the "Package" output of the card
      packages = forAllSystems (system: {
        ask-cli = (pkgsFor system).callPackage ./default.nix { };
        default = self.packages.${system}.ask-cli;
      });

      # This allows you to run it directly with 'nix run'
      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/ask";
        };
      });
    };
}
