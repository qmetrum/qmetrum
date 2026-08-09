import type { KeyboardEvent } from "react";

// Make a non-<button> element (a clickable row/card) operable by keyboard:
// spread role="button" tabIndex={0} and onKeyDown={onActivate(fn)} alongside onClick.
export function onActivate(fn: () => void) {
  return (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fn();
    }
  };
}
