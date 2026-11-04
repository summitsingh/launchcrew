import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary text-primary-foreground shadow hover:bg-primary/80',
        secondary: 'border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80',
        destructive:
          'border-transparent bg-destructive text-destructive-foreground shadow hover:bg-destructive/80',
        outline: 'text-foreground',
        success:
          'border-success/30 bg-success/10 shadow hover:bg-success/20 [color:color-mix(in_srgb,var(--success)_70%,black)] dark:[color:color-mix(in_srgb,var(--success)_80%,white)]',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {
  asChild?: boolean;
  appearance?: 'default' | 'workspace';
}

function Badge({ className, variant, asChild = false, appearance = 'default', ...props }: BadgeProps) {
  const Comp = asChild ? Slot : 'div';
  return <Comp className={cn(appearance === 'workspace' ? '' : badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
