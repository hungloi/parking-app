-- ================================================================
-- HỆ THỐNG QUẢN LÝ BÃI ĐỖ XE THÔNG MINH
-- Database: SmartParkingDB
-- Phiên bản: 5.0 - Hoàn thiện
-- Ngày: 07/12/2024
-- ================================================================


-- TẠO DATABASE MỚI
CREATE DATABASE SmartParkingDB;
GO
USE SmartParkingDB;
GO

-- ================================================================
-- BẢNG: ParkingLogs
-- ================================================================
CREATE TABLE ParkingLogs (
    id INT IDENTITY(1,1) PRIMARY KEY,
    bien_so NVARCHAR(50) NOT NULL,
    time_in DATETIME NULL DEFAULT GETDATE(),
    time_out DATETIME NULL,
    su_kien NVARCHAR(50) NULL,
    anh_bienso NVARCHAR(255) NULL,
    vi_tri_do NVARCHAR(20) NULL,
    
    CONSTRAINT CK_BienSo_NotEmpty CHECK (LEN(TRIM(bien_so)) > 0)
);
GO

-- ================================================================
-- INDEX
-- ================================================================
CREATE NONCLUSTERED INDEX IX_ParkingLogs_BienSo ON ParkingLogs(bien_so);
GO
CREATE NONCLUSTERED INDEX IX_ParkingLogs_TimeOut ON ParkingLogs(time_out) WHERE time_out IS NULL;
GO
CREATE NONCLUSTERED INDEX IX_ParkingLogs_BienSo_TimeOut ON ParkingLogs(bien_so, time_out);
GO

-- ================================================================
-- STORED PROCEDURE: Kiểm tra xe trong bãi
-- ================================================================
CREATE PROCEDURE sp_CheckVehicleInParking
    @bien_so NVARCHAR(50)
AS
BEGIN
    SET NOCOUNT ON;
    
    SELECT TOP 1
        id,
        bien_so,
        time_in,
        vi_tri_do,
        anh_bienso,
        DATEDIFF(MINUTE, time_in, GETDATE()) AS phut_da_do
    FROM ParkingLogs
    WHERE bien_so = @bien_so AND time_out IS NULL
    ORDER BY id DESC;
END;
GO

-- ================================================================
-- STORED PROCEDURE: Lưu xe VÀO
-- ================================================================
CREATE PROCEDURE sp_VehicleEntry
    @bien_so NVARCHAR(50),
    @anh_bienso NVARCHAR(255),
    @vi_tri_do NVARCHAR(20)
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Kiểm tra xe đã có trong bãi chưa
    IF EXISTS (SELECT 1 FROM ParkingLogs WHERE bien_so = @bien_so AND time_out IS NULL)
    BEGIN
        SELECT 0 AS success, N'Xe ' + @bien_so + N' đã có trong bãi!' AS message;
        RETURN;
    END
    
    -- Thêm bản ghi mới
    INSERT INTO ParkingLogs (bien_so, time_in, su_kien, anh_bienso, vi_tri_do)
    VALUES (@bien_so, GETDATE(), N'Xe vào', @anh_bienso, @vi_tri_do);
    
    -- Lấy bản ghi vừa tạo
    SELECT 
        1 AS success,
        N'Xe vào thành công!' AS message,
        id, bien_so, time_in, time_out, su_kien, anh_bienso, vi_tri_do
    FROM ParkingLogs
    WHERE id = SCOPE_IDENTITY();
END;
GO

-- ================================================================
-- STORED PROCEDURE: Lưu xe RA
-- ================================================================
CREATE PROCEDURE sp_VehicleExit
    @bien_so NVARCHAR(50),
    @anh_bienso NVARCHAR(255)
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @record_id INT;
    
    -- Tìm xe trong bãi
    SELECT TOP 1 @record_id = id
    FROM ParkingLogs 
    WHERE bien_so = @bien_so AND time_out IS NULL 
    ORDER BY id DESC;
    
    IF @record_id IS NULL
    BEGIN
        SELECT 0 AS success, N'Không tìm thấy xe ' + @bien_so + N' trong bãi!' AS message;
        RETURN;
    END
    
    -- Cập nhật thời gian ra
    UPDATE ParkingLogs
    SET time_out = GETDATE(),
        su_kien = N'Xe ra'
    WHERE id = @record_id;
    
    -- Lấy bản ghi đã cập nhật
    SELECT 
        1 AS success,
        N'Xe ra thành công!' AS message,
        id, bien_so, time_in, time_out, su_kien, anh_bienso, vi_tri_do,
        DATEDIFF(MINUTE, time_in, time_out) AS phut_do
    FROM ParkingLogs
    WHERE id = @record_id;
END;
GO

-- ================================================================
-- STORED PROCEDURE: Tìm kiếm
-- ================================================================
CREATE PROCEDURE sp_SearchVehicle
    @bien_so NVARCHAR(50)
AS
BEGIN
    SET NOCOUNT ON;
    
    SELECT *
    FROM ParkingLogs
    WHERE bien_so LIKE '%' + @bien_so + '%'
    ORDER BY id DESC;
END;
GO

-- ================================================================
-- FUNCTION: Lấy vị trí trống
-- ================================================================
CREATE FUNCTION fn_GetAvailableSlots()
RETURNS @Slots TABLE (vi_tri NVARCHAR(20))
AS
BEGIN
    DECLARE @AllSlots TABLE (vi_tri NVARCHAR(20));
    
    -- Tạo 40 vị trí (A01-A10, B01-B10, C01-C10, D01-D10)
    INSERT INTO @AllSlots
    SELECT 'A' + RIGHT('0' + CAST(n AS VARCHAR(2)), 2)
    FROM (SELECT 1 n UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 
          UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9 UNION SELECT 10) nums
    UNION ALL
    SELECT 'B' + RIGHT('0' + CAST(n AS VARCHAR(2)), 2)
    FROM (SELECT 1 n UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 
          UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9 UNION SELECT 10) nums
    UNION ALL
    SELECT 'C' + RIGHT('0' + CAST(n AS VARCHAR(2)), 2)
    FROM (SELECT 1 n UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 
          UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9 UNION SELECT 10) nums
    UNION ALL
    SELECT 'D' + RIGHT('0' + CAST(n AS VARCHAR(2)), 2)
    FROM (SELECT 1 n UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 
          UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9 UNION SELECT 10) nums;
    
    -- Loại bỏ vị trí đang dùng
    INSERT INTO @Slots
    SELECT a.vi_tri
    FROM @AllSlots a
    WHERE NOT EXISTS (
        SELECT 1 FROM ParkingLogs p 
        WHERE p.vi_tri_do = a.vi_tri AND p.time_out IS NULL
    );
    
    RETURN;
END;
GO

PRINT N'✅ Database SmartParkingDB đã được tạo thành công!';
PRINT N'✅ Sẵn sàng sử dụng!';
GO