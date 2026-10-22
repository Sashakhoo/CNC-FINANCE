import clsx from 'clsx';
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, ChevronsUpDown } from 'lucide-react';
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef, type RowSelectionState } from '@tanstack/react-table';
import { Skeleton } from './Misc';

export interface SortState { key: string; desc: boolean }

interface Props<T> {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  getId: (row: T) => string;
  total: number;
  page: number;
  pageSize: number;
  onPage: (page: number) => void;
  onPageSize?: (size: number) => void;
  sort?: SortState;
  onSort?: (s: SortState) => void;
  selectable?: boolean;
  selection?: RowSelectionState;
  onSelection?: (s: RowSelectionState) => void;
  onRowClick?: (row: T) => void;
  loading?: boolean;
  empty?: React.ReactNode;
  label: string;
}

/** Server-side paginated/sorted table on TanStack Table. Column `id` doubles as the API sort key
 *  when `meta.sortable` is true. */
export function DataGrid<T>({ data, columns, getId, total, page, pageSize, onPage, onPageSize, sort, onSort, selectable,
  selection = {}, onSelection, onRowClick, loading, empty, label }: Props<T>) {
  const allColumns: ColumnDef<T, unknown>[] = selectable ? [{
    id: '_select',
    header: ({ table }) => (
      <input type="checkbox" aria-label="Select all rows on this page" checked={table.getIsAllRowsSelected()}
        ref={(el) => { if (el) el.indeterminate = table.getIsSomeRowsSelected(); }} onChange={table.getToggleAllRowsSelectedHandler()} />
    ),
    cell: ({ row }) => (
      <input type="checkbox" aria-label="Select row" checked={row.getIsSelected()} onClick={(e) => e.stopPropagation()} onChange={row.getToggleSelectedHandler()} />
    ),
  }, ...columns] : columns;

  const table = useReactTable({
    data, columns: allColumns, getRowId: getId, getCoreRowModel: getCoreRowModel(), manualPagination: true, manualSorting: true,
    enableRowSelection: selectable, state: { rowSelection: selection },
    onRowSelectionChange: (u) => onSelection?.(typeof u === 'function' ? u(selection) : u),
  });
  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="tbl w-full border-separate border-spacing-0" aria-label={label}>
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => {
                  const sortable = (h.column.columnDef.meta as { sortable?: boolean } | undefined)?.sortable && onSort;
                  const active = sort?.key === h.column.id;
                  return (
                    <th key={h.id} className={clsx(h.column.id === '_select' && 'w-10 pl-5')}
                      aria-sort={active ? (sort!.desc ? 'descending' : 'ascending') : undefined}>
                      {sortable ? (
                        <button type="button" className="inline-flex items-center gap-1 hover:text-fg uppercase"
                          onClick={() => onSort!({ key: h.column.id, desc: active ? !sort!.desc : true })}>
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {active ? (sort!.desc ? <ArrowDown size={12} /> : <ArrowUp size={12} />) : <ChevronsUpDown size={12} className="opacity-40" />}
                        </button>
                      ) : flexRender(h.column.columnDef.header, h.getContext())}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {loading && !data.length && Array.from({ length: 6 }).map((_, i) => (
              <tr key={i}><td colSpan={allColumns.length}><Skeleton className="h-6" /></td></tr>
            ))}
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className={clsx(onRowClick && 'cursor-pointer', row.getIsSelected() && 'bg-lime-soft/40')}
                onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                onKeyDown={onRowClick ? (e) => { if (e.key === 'Enter') onRowClick(row.original); } : undefined}
                tabIndex={onRowClick ? 0 : undefined}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className={clsx(cell.column.id === '_select' && 'pl-5')}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && !data.length && empty}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 border-t border-line text-xs text-mute">
        <span>{total.toLocaleString()} {total === 1 ? 'record' : 'records'}{selectable && Object.keys(selection).length ? ` · ${Object.keys(selection).length} selected` : ''}</span>
        <div className="flex items-center gap-2">
          {onPageSize && (
            <select aria-label="Rows per page" className="h-8 rounded-full bg-s2 border border-line px-2 text-xs" value={pageSize} onChange={(e) => onPageSize(Number(e.target.value))}>
              {[25, 50, 100].map((n) => <option key={n} value={n}>{n} / page</option>)}
            </select>
          )}
          <button type="button" className="icon-btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page"><ChevronLeft size={14} /></button>
          <span className="num">{page} / {pages}</span>
          <button type="button" className="icon-btn-sm" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page"><ChevronRight size={14} /></button>
        </div>
      </div>
    </div>
  );
}
