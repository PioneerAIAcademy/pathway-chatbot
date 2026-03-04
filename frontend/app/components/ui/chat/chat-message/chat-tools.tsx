import { CalendarCardData, ToolData } from "../index";
import { CalendarCard } from "../widgets/CalendarCard";
import { WeatherCard, WeatherData } from "../widgets/WeatherCard";

export default function ChatTools({ data }: { data: ToolData }) {
  if (!data) return null;
  const { toolCall, toolOutput } = data;

  if (toolOutput.isError) {
    return (
      <div className="border-l-2 border-red-400 pl-2">
        There was an error when calling the tool {toolCall.name} with input:{" "}
        <br />
        {JSON.stringify(toolCall.input)}
      </div>
    );
  }

  switch (toolCall.name) {
    case "get_weather_information":
      const weatherData = toolOutput.output as unknown as WeatherData;
      return <WeatherCard data={weatherData} />;
    case "get_academic_calendar":
      const calendarData = toolOutput.output as unknown as CalendarCardData;
      return <CalendarCard data={calendarData} />;
    default:
      return null;
  }
}
