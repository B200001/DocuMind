import { clsx, type ClassValue } from "clsx"; 
// clsx: combines class names, skipping falsy ones (e.g. false, undefined)
import { twMerge } from "tailwind-merge"; 
// twMerge: resolves conflicting Tailwind classes (e.g. "p-2" vs "p-4") by keeping the last one

// Helper used everywhere to safely merge conditional Tailwind classes into one clean string
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs)); // first combine all class inputs, then remove any Tailwind conflicts
}
