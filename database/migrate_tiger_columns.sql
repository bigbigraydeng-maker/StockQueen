-- Migration: Add Tiger trading columns to rotation_positions
-- Run this in Supabase SQL Editor

ALTER TABLE rotation_positions
    ADD COLUMN IF NOT EXISTS quantity INTEGER,
    ADD COLUMN IF NOT EXISTS tiger_order_id VARCHAR(50),
    ADD COLUMN IF NOT EXISTS tiger_order_status VARCHAR(20),
    ADD COLUMN IF NOT EXISTS tiger_exit_order_id VARCHAR(50);

COMMENT ON COLUMN rotation_positions.quantity IS 'Number of shares (from Tiger order)';
COMMENT ON COLUMN rotation_positions.tiger_order_id IS 'Tiger buy order ID';
COMMENT ON COLUMN rotation_positions.tiger_order_status IS 'submitted/filled/cancelled';
COMMENT ON COLUMN rotation_positions.tiger_exit_order_id IS 'Tiger sell order ID';
