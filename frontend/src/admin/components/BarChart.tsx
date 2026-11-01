/** Столбчатая диаграмма на SVG без зависимостей: значения по дням, подпись при наведении. */
export function BarChart({
  points,
  label,
  format = (v: number) => String(v),
}: {
  points: { key: string; value: number; title: string }[];
  label: string;
  format?: (value: number) => string;
}) {
  const max = Math.max(1, ...points.map((p) => p.value));
  const width = 100 / Math.max(1, points.length);
  return (
    <figure className="flex flex-col gap-1">
      <svg
        role="img"
        aria-label={label}
        viewBox="0 0 100 40"
        preserveAspectRatio="none"
        className="h-28 w-full"
      >
        {points.map((p, i) => {
          const height = (p.value / max) * 38;
          return (
            <rect
              key={p.key}
              x={i * width + width * 0.15}
              y={40 - height}
              width={width * 0.7}
              height={height}
              className="fill-primary/70 hover:fill-primary"
            >
              <title>{`${p.title}: ${format(p.value)}`}</title>
            </rect>
          );
        })}
      </svg>
      <figcaption className="flex justify-between text-xs text-muted-foreground">
        <span>{points[0]?.title}</span>
        <span>max {format(max)}</span>
        <span>{points[points.length - 1]?.title}</span>
      </figcaption>
    </figure>
  );
}
