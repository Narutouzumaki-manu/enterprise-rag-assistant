import { describe, it, expect } from 'vitest';
import { validateFile, MAX_UPLOAD_BYTES } from '../api/upload';
import { getStatusDisplay } from '../components/DocumentRow';

describe('validateFile', () => {
  it('accepts valid PDF files under 25 MB', () => {
    const file = new File(['dummy pdf content'], 'report.pdf', {
      type: 'application/pdf',
    });
    expect(validateFile(file)).toBeNull();
  });

  it('accepts valid DOCX files under 25 MB', () => {
    const file = new File(['dummy docx content'], 'contract.docx', {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    });
    expect(validateFile(file)).toBeNull();
  });

  it('accepts valid CSV files under 25 MB', () => {
    const file = new File(['a,b,c\n1,2,3'], 'data.csv', {
      type: 'text/csv',
    });
    expect(validateFile(file)).toBeNull();
  });

  it('is case-insensitive for file extensions (e.g. .PDF, .DocX)', () => {
    const fileUpper = new File(['content'], 'FINANCIALS.PDF', {
      type: 'application/pdf',
    });
    expect(validateFile(fileUpper)).toBeNull();

    const fileMixed = new File(['content'], 'Summary.DocX', {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    });
    expect(validateFile(fileMixed)).toBeNull();
  });

  it('rejects unsupported file extensions (e.g. .txt, .png, .exe, .xlsx)', () => {
    const txtFile = new File(['text'], 'notes.txt', { type: 'text/plain' });
    const err = validateFile(txtFile);
    expect(err).toContain('not a supported type');
    expect(err).toContain('notes.txt');

    const pngFile = new File(['png'], 'image.png', { type: 'image/png' });
    expect(validateFile(pngFile)).toContain('not a supported type');
  });

  it('rejects files larger than 25 MB', () => {
    const oversizedFile = {
      name: 'huge_document.pdf',
      size: MAX_UPLOAD_BYTES + 1024, // 25MB + 1KB
    } as File;

    const err = validateFile(oversizedFile);
    expect(err).toContain('25 MB or smaller');
    expect(err).toContain('huge_document.pdf');
  });

  it('accepts files exactly at the 25 MB limit', () => {
    const exactFile = {
      name: 'exact_document.pdf',
      size: MAX_UPLOAD_BYTES,
    } as File;

    expect(validateFile(exactFile)).toBeNull();
  });
});

describe('getStatusDisplay', () => {
  it('returns exact contract text for all 7 statuses', () => {
    expect(getStatusDisplay('queued', null).text).toBe(
      'Waiting to be processed...',
    );
    expect(getStatusDisplay('parsing', null).text).toBe('Reading document...');
    expect(getStatusDisplay('indexing', null).text).toBe(
      'Making it searchable...',
    );
    expect(getStatusDisplay('success', null).text).toBe('Ready');
    expect(getStatusDisplay('partial', null).text).toBe(
      'Partly processed: some pages could not be read',
    );
    expect(getStatusDisplay('duplicate', null).text).toBe(
      'This document was already uploaded',
    );
    expect(
      getStatusDisplay('failed', 'Scanned PDF: no OCR supported').text,
    ).toBe('Scanned PDF: no OCR supported');
  });

  it('includes an icon for non-color accessibility across all statuses', () => {
    const statuses = [
      'queued',
      'parsing',
      'indexing',
      'success',
      'partial',
      'duplicate',
      'failed',
    ] as const;

    for (const st of statuses) {
      const display = getStatusDisplay(st, 'err');
      expect(display.icon.length).toBeGreaterThan(0);
    }
  });
});

