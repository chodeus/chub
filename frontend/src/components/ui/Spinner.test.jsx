/** Guards the inline spinner as one aligned unit whose label takes the caller's font size. */
import { render, screen } from '@testing-library/react';
import Spinner from './Spinner.jsx';

const SIZE = /^text-(xs|sm|base|lg|[2-9]?xl|micro|meta|dense|heading|title|stat|\[)/;

it('renders inline as one aligned unit that sets no font size', () => {
    const { container } = render(<Spinner size="small" text="Loading…" />);
    expect(container.childNodes).toHaveLength(1);
    const root = container.firstChild;
    expect(root.tagName).toBe('SPAN');
    expect([...root.classList]).toEqual(
        expect.arrayContaining(['inline-flex', 'items-center', 'gap-2'])
    );
    expect(root.textContent).toBe('Loading…');
    const classes = [...container.querySelectorAll('*')].flatMap(el => [...el.classList]);
    expect(classes.filter(c => SIZE.test(c))).toEqual([]);
});

it('takes the font size from className on the inline unit', () => {
    const { container } = render(<Spinner size="small" text="Loading…" className="text-xs" />);
    expect(container.firstChild.classList).toContain('text-xs');
});

it('announces a spinner with text as a status and leaves a bare ring out', () => {
    const { rerender } = render(<Spinner size="small" text="Loading…" />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading…');
    rerender(<Spinner center text="Loading…" />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading…');
    rerender(<Spinner size="small" />);
    expect(screen.queryByRole('status')).toBeNull();
});

it('hides the ring from assistive tech', () => {
    const { container } = render(<Spinner size="small" text="Loading…" />);
    expect(container.querySelector('.animate-spin')).toHaveAttribute('aria-hidden', 'true');
});

it('keeps the centred label at text-sm', () => {
    const { getByText } = render(<Spinner center text="Loading…" />);
    expect(getByText('Loading…').classList).toContain('text-sm');
});
