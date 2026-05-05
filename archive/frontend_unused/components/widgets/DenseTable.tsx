"use client";

import React, { useMemo, useState } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";

type SortDirection = "asc" | "desc";

export type DenseTableColumn<T> = {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
  sortAccessor?: (row: T) => string | number | null | undefined;
  headerClassName?: string;
  cellClassName?: string;
};

type DenseTableProps<T> = {
  rows: T[];
  columns: Array<DenseTableColumn<T>>;
  rowKey: (row: T, idx: number) => string | number;
  emptyMessage?: string;
  defaultSortKey?: string;
  defaultSortDirection?: SortDirection;
};

function compareSortValues(
  a: string | number | null | undefined,
  b: string | number | null | undefined,
): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { sensitivity: "base", numeric: true });
}

export function DenseTable<T>({
  rows,
  columns,
  rowKey,
  emptyMessage = "No rows",
  defaultSortKey,
  defaultSortDirection = "desc",
}: DenseTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | undefined>(defaultSortKey);
  const [sortDirection, setSortDirection] = useState<SortDirection>(defaultSortDirection);

  const sortedRows = useMemo(() => {
    if (!sortKey) return rows;
    const col = columns.find((c) => c.key === sortKey);
    if (!col?.sortAccessor) return rows;
    const next = [...rows].sort((left, right) =>
      compareSortValues(col.sortAccessor?.(left), col.sortAccessor?.(right)),
    );
    return sortDirection === "asc" ? next : next.reverse();
  }, [rows, columns, sortKey, sortDirection]);

  const setSort = (column: DenseTableColumn<T>) => {
    if (!column.sortAccessor) return;
    if (sortKey === column.key) {
      setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(column.key);
    setSortDirection("desc");
  };

  return (
    <div className="overflow-x-auto rounded-xl border border-white/8 bg-white/[0.015]">
      <table className="min-w-full text-left text-sm">
        <thead className="sticky top-0 z-[1] border-b border-white/10 bg-[linear-gradient(180deg,rgba(23,34,54,0.96),rgba(16,24,40,0.94))] text-xs uppercase tracking-wider text-[color:var(--text-muted)] backdrop-blur">
          <tr>
            {columns.map((column) => {
              const isActiveSort = sortKey === column.key;
              const sortable = Boolean(column.sortAccessor);
              return (
                <th key={column.key} className={["px-0 py-2.5", column.headerClassName].filter(Boolean).join(" ")}>
                  {sortable ? (
                    <button
                      type="button"
                      onClick={() => setSort(column)}
                      className="inline-flex items-center gap-1 rounded-md px-1 text-[color:var(--text-muted)] hover:text-white"
                    >
                      <span>{column.header}</span>
                      {isActiveSort ? (
                        sortDirection === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                      ) : null}
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row, idx) => (
            <tr key={rowKey(row, idx)} className="border-t border-white/6 transition-colors hover:bg-[#0080FF]/[0.06]">
              {columns.map((column) => (
                <td key={column.key} className={["py-2.5", column.cellClassName].filter(Boolean).join(" ")}>
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
          {!sortedRows.length ? (
            <tr>
              <td colSpan={columns.length} className="py-12 text-center text-sm text-[color:var(--text-muted)]">
                {emptyMessage}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
