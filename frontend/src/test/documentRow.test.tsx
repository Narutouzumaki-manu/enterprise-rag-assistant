import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DocumentRow } from '../components/DocumentRow';
import type { Document } from '../api/types';

describe('DocumentRow component', () => {
  const baseDoc: Document = {
    document_id: 'doc-123',
    filename: 'quarterly_report.pdf',
    status: 'success',
    error_message: null,
    source_type: 'pdf',
    created_at: '2026-10-31T00:00:00Z',
    uploaded_by_me: true,
  };

  it('renders filename, source type, formatted date, and status', () => {
    render(
      <table>
        <tbody>
          <DocumentRow
            doc={baseDoc}
            onDelete={vi.fn()}
            isDeleting={false}
            deleteError={null}
          />
        </tbody>
      </table>,
    );

    expect(screen.getByText('quarterly_report.pdf')).toBeInTheDocument();
    expect(screen.getByText('pdf')).toBeInTheDocument();
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });

  it('renders delete button when uploaded_by_me is true', () => {
    render(
      <table>
        <tbody>
          <DocumentRow
            doc={baseDoc}
            onDelete={vi.fn()}
            isDeleting={false}
            deleteError={null}
          />
        </tbody>
      </table>,
    );

    const deleteBtn = screen.getByRole('button', {
      name: /delete quarterly_report.pdf/i,
    });
    expect(deleteBtn).toBeInTheDocument();
  });

  it('does NOT render delete button when uploaded_by_me is false', () => {
    const otherUserDoc: Document = {
      ...baseDoc,
      document_id: 'doc-456',
      filename: 'other_user_file.pdf',
      uploaded_by_me: false,
    };

    render(
      <table>
        <tbody>
          <DocumentRow
            doc={otherUserDoc}
            onDelete={vi.fn()}
            isDeleting={false}
            deleteError={null}
          />
        </tbody>
      </table>,
    );

    expect(
      screen.queryByRole('button', { name: /delete/i }),
    ).not.toBeInTheDocument();
  });

  it('shows confirmation dialog before triggering delete', async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn().mockResolvedValue(undefined);

    render(
      <table>
        <tbody>
          <DocumentRow
            doc={baseDoc}
            onDelete={onDelete}
            isDeleting={false}
            deleteError={null}
          />
        </tbody>
      </table>,
    );

    const initialDeleteBtn = screen.getByRole('button', {
      name: /delete quarterly_report.pdf/i,
    });
    await user.click(initialDeleteBtn);

    // Confirmation dialog appears
    const confirmBtn = screen.getByRole('button', { name: /yes, delete/i });
    const cancelBtn = screen.getByRole('button', { name: /cancel/i });
    expect(confirmBtn).toBeInTheDocument();
    expect(cancelBtn).toBeInTheDocument();
    expect(onDelete).not.toHaveBeenCalled();

    // Confirming triggers onDelete
    await user.click(confirmBtn);
    expect(onDelete).toHaveBeenCalledWith('doc-123');
  });

  it('dismisses confirmation dialog on cancel without deleting', async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();

    render(
      <table>
        <tbody>
          <DocumentRow
            doc={baseDoc}
            onDelete={onDelete}
            isDeleting={false}
            deleteError={null}
          />
        </tbody>
      </table>,
    );

    await user.click(
      screen.getByRole('button', { name: /delete quarterly_report.pdf/i }),
    );
    await user.click(screen.getByRole('button', { name: /cancel/i }));

    expect(onDelete).not.toHaveBeenCalled();
    expect(
      screen.getByRole('button', { name: /delete quarterly_report.pdf/i }),
    ).toBeInTheDocument();
  });
});

