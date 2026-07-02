import { LibraryBig, MessageSquare, type LucideIcon } from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/library", label: "Library", icon: LibraryBig },
  { href: "/chat", label: "Chat", icon: MessageSquare },
];
