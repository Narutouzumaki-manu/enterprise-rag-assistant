// ─────────────────────────────────────────────────────────────────────────────
// NavBar.tsx — Persistent header navigation with Chat, Documents, and Log out.
// Keyboard reachable, responsive down to 360px with mobile drawer.
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

export function NavBar() {
  const { logout } = useAuth();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    if (!mobileMenuOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setMobileMenuOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [mobileMenuOpen]);

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-2 min-h-[40px] inline-flex items-center rounded-md text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:focus-visible:ring-blue-400 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-gray-900 ${
      isActive
        ? 'bg-blue-100 text-blue-900 dark:bg-blue-900/50 dark:text-blue-100 font-semibold'
        : 'text-gray-700 hover:text-gray-900 hover:bg-gray-100 dark:text-gray-300 dark:hover:text-white dark:hover:bg-gray-800'
    }`;

  const mobileNavLinkClass = ({ isActive }: { isActive: boolean }) =>
    `block px-3 py-2.5 min-h-[40px] flex items-center rounded-md text-base font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:focus-visible:ring-blue-400 ${
      isActive
        ? 'bg-blue-100 text-blue-900 dark:bg-blue-900/50 dark:text-blue-100 font-semibold'
        : 'text-gray-700 hover:text-gray-900 hover:bg-gray-100 dark:text-gray-300 dark:hover:text-white dark:hover:bg-gray-800'
    }`;

  return (
    <nav
      aria-label="Main Navigation"
      className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 sticky top-0 z-30"
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center space-x-3">
            <span className="text-lg font-bold text-gray-900 dark:text-white">
              Enterprise RAG
            </span>
            <div className="hidden sm:flex sm:space-x-2 sm:ml-6">
              <NavLink to="/chat" className={navLinkClass}>
                Chat
              </NavLink>
              <NavLink to="/documents" className={navLinkClass}>
                Documents
              </NavLink>
            </div>
          </div>

          <div className="hidden sm:flex sm:items-center">
            <button
              type="button"
              onClick={logout}
              className="px-3 py-2 min-h-[40px] inline-flex items-center border border-gray-300 dark:border-gray-700 rounded-md text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-blue-500 dark:focus-visible:ring-blue-400 dark:focus-visible:ring-offset-gray-900 transition-colors"
            >
              Log out
            </button>
          </div>

          {/* Mobile menu hamburger button */}
          <div className="flex sm:hidden">
            <button
              type="button"
              onClick={() => setMobileMenuOpen((open) => !open)}
              aria-controls="mobile-menu"
              aria-expanded={mobileMenuOpen}
              aria-label="Toggle navigation menu"
              className="inline-flex items-center justify-center p-2 min-h-[40px] min-w-[40px] rounded-md text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:focus-visible:ring-blue-400"
            >
              <span className="sr-only">Open main menu</span>
              {mobileMenuOpen ? (
                <svg
                  className="block h-6 w-6"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="2"
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              ) : (
                <svg
                  className="block h-6 w-6"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="2"
                    d="M4 6h16M4 12h16M4 18h16"
                  />
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile menu drawer */}
      {mobileMenuOpen && (
        <div className="sm:hidden border-t border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900" id="mobile-menu">
          <div className="px-2 pt-2 pb-3 space-y-1">
            <NavLink
              to="/chat"
              onClick={() => setMobileMenuOpen(false)}
              className={mobileNavLinkClass}
            >
              Chat
            </NavLink>
            <NavLink
              to="/documents"
              onClick={() => setMobileMenuOpen(false)}
              className={mobileNavLinkClass}
            >
              Documents
            </NavLink>
            <div className="pt-2 border-t border-gray-200 dark:border-gray-800">
              <button
                type="button"
                onClick={() => {
                  setMobileMenuOpen(false);
                  logout();
                }}
                className="w-full text-left px-3 py-2.5 min-h-[40px] flex items-center rounded-md text-base font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
              >
                Log out
              </button>
            </div>
          </div>
        </div>
      )}
    </nav>
  );
}

