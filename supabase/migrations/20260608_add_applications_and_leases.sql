-- Create applications table
CREATE TABLE IF NOT EXISTS applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    renter_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    application_data JSONB,
    approved_by UUID REFERENCES profiles(id),
    approved_at TIMESTAMP WITH TIME ZONE,
    denied_by UUID REFERENCES profiles(id),
    denial_reason TEXT,
    denied_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(property_id, renter_id)
);

-- Create leases table
CREATE TABLE IF NOT EXISTS leases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    renter_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    landlord_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    lease_terms JSONB,
    status VARCHAR(20) NOT NULL DEFAULT 'unsigned',
    signed_by JSONB DEFAULT '{}',
    signed_at TIMESTAMP WITH TIME ZONE,
    termination_reason TEXT,
    terminated_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create indexes for better query performance
CREATE INDEX idx_applications_property_id ON applications(property_id);
CREATE INDEX idx_applications_renter_id ON applications(renter_id);
CREATE INDEX idx_applications_status ON applications(status);
CREATE INDEX idx_leases_property_id ON leases(property_id);
CREATE INDEX idx_leases_renter_id ON leases(renter_id);
CREATE INDEX idx_leases_landlord_id ON leases(landlord_id);
CREATE INDEX idx_leases_status ON leases(status);

-- Update tours table to include visitor_id if it doesn't exist
ALTER TABLE tours ADD COLUMN IF NOT EXISTS visitor_id UUID REFERENCES profiles(id);
ALTER TABLE tours ADD COLUMN IF NOT EXISTS denial_reason TEXT;
