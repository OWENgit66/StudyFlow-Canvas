import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ResourceItem } from "@/components/resource-item";
import { resource } from "./fixtures";

it.each([['lecture', 'Lecture'], ['tutorial', 'Tutorial'], ['other', 'Other material']] as const)(
  'labels %s materials without changing source links', (resource_type, label) => {
    render(<ResourceItem resource={{ ...resource, resource_type }} />);
    expect(screen.getByText(label)).toBeVisible();
    expect(screen.getByRole('heading', { name: resource.filename })).toBeVisible();
    expect(screen.getByRole('link', { name: /Open/ })).toHaveAttribute('href', '/api/resources/7/file');
    expect(screen.getByRole('link', { name: 'Download' })).toBeVisible();
  }
);
