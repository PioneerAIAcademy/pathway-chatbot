import Image from "next/image";
import { SettingsMenu } from "./settings-menu";

export default function Header() {
  return (
    <header className="w-full bg-[#FFC328] px-4 sm:px-6 pb-2 pt-0 min-[480px]:pt-2 min-[480px]:pb-2 flex-shrink-0">
      {/* Container for screens >= 480px - single row layout */}
      <div className="hidden min-[480px]:flex items-center justify-between w-full relative min-h-[40px]">
        {/* Logo */}
        <div className="flex items-center z-10">
          <a href="/" className="cursor-pointer">
            <Image
              src="/pathway-horizontal-logo.png"
              alt="BYU Pathway Logo"
              width={140}
              height={18}
              className="h-[15px] sm:h-[24px] min-[570px]:h-[20px] w-auto"
            />
          </a>
        </div>
        
        {/* Title - centered */}
        <div className="absolute left-1/2 transform -translate-x-1/2">
          <h1 className="font-semibold text-[18px] md:text-xl text-[#454540] whitespace-nowrap">
            Missionary Assistant
          </h1>
        </div>
        
        {/* Right side - Settings menu (all screens) */}
        <div className="flex items-center gap-1 sm:gap-2 z-10">
          <SettingsMenu />
        </div>
      </div>

      {/* Container for screens < 480px - wrapped layout */}
      <div className="min-[480px]:hidden relative -ml-2">
        {/* Logo - top left */}
        <a href="/" className="cursor-pointer inline-block">
          <Image
            src="/pathway-horizontal-logo.png"
            alt="BYU Pathway Logo"
            width={140}
            height={18}
            className="h-[14px] w-auto"
          />
        </a>
        
        {/* Settings Icon - absolute positioned, vertically centered */}
        <div className="absolute right-0 top-1/2 -translate-y-1/2 z-50">
          <SettingsMenu />
        </div>
        
        {/* Title - below logo */}
        <div className="w-full mt-1.5">
          <h1 className="font-semibold text-[18px] text-[#454540] -mt-2 text-center leading-tight">
            Missionary Assistant
          </h1>
        </div>
      </div>
    </header>
  );
}
