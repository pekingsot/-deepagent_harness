import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

// shadcn/ui Native Select：使用浏览器原生选项交互，不自行实现下拉逻辑。
export function NativeSelect({ className, ...props }: React.ComponentProps<"select">) {
  return <div className="relative"><select data-slot="native-select" className={cn("h-9 w-full appearance-none rounded-md border bg-background py-2 pr-9 pl-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50", className)} {...props} /><ChevronDown aria-hidden className="pointer-events-none absolute right-3 top-3 size-3.5 text-muted-foreground" /></div>;
}
