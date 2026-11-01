const MAX_ROWS = 500;

/** Разбор CSV/TSV для просмотра: кавычки по RFC 4180, разделитель — по первой строке. */
export function parseDelimited(text: string, ext: string): string[][] {
  const first = text.split("\n", 1)[0] ?? "";
  const delimiter =
    ext === "tsv" ? "\t" : first.split(";").length > first.split(",").length ? ";" : ",";
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length && rows.length < MAX_ROWS; i += 1) {
    const char = text.charAt(i);
    if (quoted) {
      if (char === '"' && text.charAt(i + 1) === '"') {
        cell += '"';
        i += 1;
      } else if (char === '"') quoted = false;
      else cell += char;
    } else if (char === '"') quoted = true;
    else if (char === delimiter) {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      cell = "";
    } else cell += char;
  }
  if (cell || row.length) rows.push([...row, cell.replace(/\r$/, "")]);
  return rows;
}
