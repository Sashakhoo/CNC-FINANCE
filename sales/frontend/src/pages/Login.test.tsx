// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Login from './Login';

function renderLogin() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><Login /></QueryClientProvider>);
}

const json = (status: number, body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));

describe('Login', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it('validates before calling the API', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(() => json(200, { needs_setup: false, finance_url: '' }));
    renderLogin();
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(await screen.findByText('Enter your username')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/auth/login'))).toBe(false);
  });

  it('shows the error Finance returns', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) =>
      String(url).includes('/auth/login') ? json(401, { detail: 'Invalid username or password' }) : json(200, { needs_setup: false, finance_url: '' }));
    renderLogin();
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'owner' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('Invalid username or password'));
  });

  it('points to Finance when no account exists yet', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => json(200, { needs_setup: true, finance_url: 'https://finance.example' }));
    renderLogin();
    expect(await screen.findByText('No accounts yet.')).toBeTruthy();
  });
});
