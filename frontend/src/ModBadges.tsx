interface ModBadgesProps {
  mods: readonly string[];
  className?: string;
}

function modClassName(mod: string): string {
  return `mod-${mod.toLowerCase().replace(/[^a-z0-9]/g, "")}`;
}

function ModBadges({ mods, className }: ModBadgesProps) {
  const displayedMods = mods.length > 0 ? mods : ["NM"];
  const combinationClassName = ["mod-combination", className]
    .filter(Boolean)
    .join(" ");

  return (
    <span className={combinationClassName}>
      {displayedMods.map((mod, index) => (
        <span className={`mod-badge ${modClassName(mod)}`} key={`${mod}-${index}`}>
          {mod}
        </span>
      ))}
    </span>
  );
}

export default ModBadges;
