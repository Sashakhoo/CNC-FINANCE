// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGrid } from './DataGrid';
import { MaybeScore } from './Badges';
import { WorkspaceCard } from '../crm/WorkspaceCard';
import type { Prospect } from '../../types';

afterEach(() => cleanup());

type Row = { id: number; name: string };
const cols: ColumnDef<Row, unknown>[] = [{ id: 'name', header: 'Name', meta: { sortable: true }, cell: ({ row }) => row.original.name }];

describe('DataGrid', () => {
  it('drives server-side sort, paging and selection', () => {
    const onSort = vi.fn(); const onPage = vi.fn(); const onSelection = vi.fn();
    render(<DataGrid label="t" data={[{ id: 1, name: 'A' }, { id: 2, name: 'B' }]} columns={cols} getId={(r) => String(r.id)}
      total={60} page={1} pageSize={25} onPage={onPage} sort={{ key: 'name', desc: false }} onSort={onSort}
      selectable selection={{}} onSelection={onSelection} />);
    fireEvent.click(screen.getByRole('button', { name: /name/i }));
    expect(onSort).toHaveBeenCalledWith({ key: 'name', desc: true });
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
    expect(onPage).toHaveBeenCalledWith(2);
    expect((screen.getByRole('button', { name: 'Previous page' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getAllByRole('checkbox', { name: 'Select row' })[0]);
    expect(onSelection).toHaveBeenCalledWith({ 1: true });
    expect(screen.getByText('1 / 3')).toBeTruthy();
  });
});

describe('MaybeScore', () => {
  it('shows a dash, never a number, when not calculated', () => {
    render(<MaybeScore value={null} title="Lead score" />);
    expect(screen.getByText('—').getAttribute('title')).toContain('not calculated');
  });
});

function prospect(over: Partial<Prospect> = {}): Prospect {
  return {
    id: 7, full_name: 'Jane Tan', original_title: 'HR Manager', normalized_title: 'HR Manager', department: 'HR', seniority: 'Manager',
    status: 'REVIEW', status_changed_at: null, last_contacted_at: null, follow_up_at: '2026-10-28T06:00:00Z', created_at: '2026-10-01T00:00:00Z',
    company: { id: 1, legal_name: 'Acme Sdn Bhd', display_name: 'Acme Sdn Bhd', industry: 'Automation', employee_estimate: 200, domain: 'acme.example', deal_value: null },
    location: null, email: 'jane@acme.example', email_status: 'UNVERIFIED', email_provenance: 'DISCOVERED', profile_url: null,
    lead_score: null, priority: null, contact_confidence: null, training_program: null, match_score: null, source_count: 2, suppressed: false, ...over,
  };
}

function renderCard(p: Prospect) {
  return render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><WorkspaceCard p={p} canEdit /></MemoryRouter></QueryClientProvider>);
}

describe('WorkspaceCard', () => {
  it('shows the stage next step and real follow-up date, with a mailto link', () => {
    renderCard(prospect());
    expect(screen.getByText('Review Lead Fit')).toBeTruthy();
    expect(screen.getByText(/28 10 2026/)).toBeTruthy();
    expect(screen.getByRole('link', { name: /Email Jane Tan/ }).getAttribute('href')).toBe('mailto:jane%40acme.example');
  });
  it('blocks email and scheduling for Do Not Contact', () => {
    renderCard(prospect({ status: 'DO_NOT_CONTACT', suppressed: true, follow_up_at: null }));
    expect(screen.queryByRole('link', { name: /Email Jane Tan/ })).toBeNull();
    expect(screen.getByLabelText('Email blocked: Do Not Contact')).toBeTruthy();
    expect((screen.getByRole('button', { name: /Schedule a call/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('No follow-up scheduled')).toBeTruthy();
  });
});
