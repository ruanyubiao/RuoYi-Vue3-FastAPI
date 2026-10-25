-- auto-generated, do not edit by hand
-- new database only: patches already merged into ruoyi-fastapi-my.sql are recorded as BASELINE
set names utf8mb4;
create table if not exists schema_version (version varchar(32) not null primary key comment 'patch version from the file name, e.g. 0001', script varchar(255) not null comment 'patch file name', checksum char(64) not null comment 'SHA-256 of the patch file', type varchar(16) not null comment 'BASELINE: merged into the init SQL; SQL: applied by db_patches_apply', success tinyint not null comment '1 applied, 0 failed', installed_on datetime not null default current_timestamp comment 'when recorded') engine=innodb default charset=utf8mb4 comment='applied db patches';
insert into schema_version(version, script, checksum, type, success) values ('0001', 'V0001__debug_numconv_menu.sql', 'c72e55a1bf78feaf3c3a33dfdf3d7a8dc88c19143da7f517e4b67d45907adc0f', 'BASELINE', 1);
insert into schema_version(version, script, checksum, type, success) values ('0002', 'V0002__debug_timeconv_menu.sql', '7112b42c9db4260b0931b1f9dbe92da0e9ecca5d6b848a7c921180b0bb17dfd4', 'BASELINE', 1);
