"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogTitle = DialogPrimitive.Title;
export const DialogDescription = DialogPrimitive.Description;

export function DialogContent({ className, children, ...props }: React.ComponentProps<typeof DialogPrimitive.Content>) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/25 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in-0" />
      <DialogPrimitive.Content className={cn("fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl border bg-background p-6 shadow-xl outline-none data-[state=open]:animate-in data-[state=open]:zoom-in-95", className)} {...props}>
        {children}
        <DialogPrimitive.Close aria-label="关闭" className="absolute right-4 top-4 rounded-md p-1 text-muted-foreground hover:bg-accent focus-visible:ring-2"><X className="size-4" /></DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
