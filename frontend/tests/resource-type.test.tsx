import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { ResourceItem } from "@/components/resource-item";
import { resource } from "./fixtures";

it.each(['lecture', 'tutorial', 'other'] as const)(
  'labels %s materials without changing source links', (resource_type) => {
    render(<ResourceItem resource={{ ...resource, resource_type }} />);
    expect(screen.getByRole('combobox', { name: `Material type for ${resource.filename}` })).toHaveValue(resource_type);
    expect(screen.getByRole('heading', { name: resource.filename })).toBeVisible();
    expect(screen.getByRole('link', { name: /Open/ })).toHaveAttribute('href', '/api/resources/7/file');
    expect(screen.getByRole('link', { name: 'Download' })).toBeVisible();
  }
);

it('saves manual classification and keeps the saved value on a fresh render', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: resource.id, resource_type: 'lecture', classification_source: 'manual' })));
  vi.stubGlobal('fetch', fetch);
  const view = render(<ResourceItem resource={{ ...resource, resource_type: 'other' }} />);
  await userEvent.selectOptions(screen.getByRole('combobox'), 'lecture');
  expect(await screen.findByRole('combobox')).toHaveValue('lecture');
  expect(fetch).toHaveBeenCalledExactlyOnceWith(`/api/resources/${resource.id}/classification`, expect.objectContaining({
    method: 'PATCH', body: JSON.stringify({ resource_type: 'lecture' }),
  }));
  view.unmount();
  render(<ResourceItem resource={{ ...resource, resource_type: 'lecture', classification_source: 'manual' }} />);
  expect(screen.getByRole('combobox')).toHaveValue('lecture');
});

it('retains the original type on a failed save and displays a safe error', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private error', { status: 500 })));
  render(<ResourceItem resource={{ ...resource, resource_type: 'tutorial' }} />);
  await userEvent.selectOptions(screen.getByRole('combobox'), 'lecture');
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save');
  expect(screen.getByRole('combobox')).toHaveValue('tutorial');
  expect(document.body.textContent).not.toContain('private error');
});

it('disables classification while saving and shows loading status', async () => {
  let resolve!: (value: Response) => void;
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(done => { resolve = done; })));
  render(<ResourceItem resource={{ ...resource, resource_type: 'other' }} />);
  await userEvent.selectOptions(screen.getByRole('combobox'), 'lecture');
  expect(screen.getByRole('combobox')).toBeDisabled();
  expect(screen.getByRole('status')).toHaveTextContent('Saving');
  resolve(new Response(JSON.stringify({ id: resource.id, resource_type: 'lecture', classification_source: 'manual' })));
  await screen.findByRole('combobox', { name: `Material type for ${resource.filename}` });
  expect(await screen.findByDisplayValue('Lecture')).toBeEnabled();
});
